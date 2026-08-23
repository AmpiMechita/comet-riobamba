import ast
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from services.captcha_math_solver import solve_captcha_math
# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("services.challenge_solver")

# Corpus de challenges reales: append atomico (una linea por intento) + fail-open.
# Ruta overrideable via env CAPTCHA_SAMPLES_PATH (para aislar tests de produccion).
_CAPTCHA_SAMPLES_PATH = Path(os.environ.get(
    "CAPTCHA_SAMPLES_PATH",
    str(Path(__file__).resolve().parents[1] / "data" / "captcha_samples.jsonl"),
))


def _append_captcha_sample(sample: Dict[str, Any]) -> None:
    """Append atomico y fail-open de una muestra al corpus de challenges.

    Un error de escritura/logging NUNCA debe romper el flujo de verificacion:
    cualquier excepcion se traga aqui dentro.
    """
    try:
        _CAPTCHA_SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CAPTCHA_SAMPLES_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
            fh.flush()
    except Exception as _e:
        logger.debug("ChallengeSolver: no se pudo registrar sample de captcha (fail-open): %s", _e)

class ChallengeSolver:
    @staticmethod
    def _fix_mojibake(text: str) -> str:
        if not text:
            return text
        current = text
        for _ in range(3):
            try:
                fixed = current.encode("cp1252", errors="strict").decode("utf-8", errors="strict")
            except Exception:
                break
            if fixed == current:
                break
            current = fixed
        return current

    @staticmethod
    def _normalize_math_text(text: str) -> str:
        if not text:
            return text
        replacements = {
            "\u00d7": "*",
            "\u00f7": "/",
            "\u2212": "-",
            "\u2013": "-",
            "\u2014": "-",
        }
        result = text
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result

    @staticmethod
    def _safe_eval_expression(expr: str) -> Optional[float]:
        try:
            if not expr:
                return None
            tree = ast.parse(expr.strip(), mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp):
                    if type(node.op) not in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod):
                        return None
                elif isinstance(node, ast.UnaryOp):
                    if type(node.op) not in (ast.USub,):
                        return None
                elif isinstance(node, (ast.Expression, ast.Constant, ast.operator, ast.unaryop)):
                    continue
                else:
                    return None
            code = compile(tree, "<captcha>", "eval")
            result = eval(code)
            if isinstance(result, (int, float)):
                return float(result)
            return None
        except Exception:
            return None

    async def _extract_and_eval_with_llm(self, challenge_text: str) -> Optional[str]:
        if not self.model_cascade:
            logger.error("ChallengeSolver: ModelCascade no disponible para _extract_and_eval_with_llm.")
            return None
        prompt = (
            "Extract ONLY the mathematical expression from the text below. "
            "Return ONLY the expression in simple Python notation "
            "(e.g. '15 + 23', '7 * 4.5', '100 / 4 + 3'). "
            "No explanation, no units, no equals sign, no result.\n\n"
            f"Text: {challenge_text}"
        )
        try:
            response = await self._generate_with_captcha_fallback(
                prompt=prompt,
                system_prompt="You output ONLY the expression. No text, no explanation."
            )
            expr = response.strip()
            self._last_extracted_expr = expr
            logger.info(f"ChallengeSolver: LLM extrajo expresion '{expr}'")
            result = self._safe_eval_expression(expr)
            if result is not None:
                answer = f"{result:.2f}"
                logger.info(f"ChallengeSolver: LLM+eval exito! '{expr}' = {answer}")
                return answer
            logger.warning(f"ChallengeSolver: safe_eval no pudo evaluar '{expr}'")
            return None
        except Exception as e:
            logger.error(f"ChallengeSolver: Error en _extract_and_eval_with_llm: {e}")
            return None

    def __init__(self, moltbook_client, model_cascade=None):
        self.moltbook = moltbook_client
        self.model_cascade = model_cascade
        self._last_native_expr = None
        self._last_extracted_expr = None
        self._last_llm_raw = None

    async def solve_and_verify(self, challenge_data: Dict[str, Any]) -> bool:
        verification_code = challenge_data.get("verification_code")
        challenge_text = challenge_data.get("challenge_text", "")

        def _record_sample(extracted_expr, answer_calc, submit_status, server_message, verified, result=None) -> None:
            """Corpus de challenges: append atomico + fail-open. Nunca rompe el flujo."""
            content_id = challenge_data.get("content_id") or challenge_data.get("post_id")
            raw = (result or {}).get("raw") if isinstance(result, dict) else None
            if not content_id and isinstance(raw, dict):
                content_id = raw.get("content_id")
            _append_captcha_sample({
                "ts": datetime.now(timezone.utc).isoformat(),
                "content_id": content_id,
                "challenge_text": repr(challenge_text),
                "extracted_expr": extracted_expr,
                "answer_calc": answer_calc,
                "submit_status": submit_status,
                "server_message": server_message,
                "verified": bool(verified),
            })

        if not challenge_text or not verification_code:
            logger.warning("ChallengeSolver: datos incompletos.")
            return False

        self._last_native_expr = None
        self._last_extracted_expr = None
        self._last_llm_raw = None
        llm_attempted = False

        logger.info("ChallengeSolver: Intentando resolver CAPTCHA nativamente con Python...")
        answer = solve_captcha_math(challenge_text) or self._solve_native_math(challenge_text)
        extracted_expr = self._last_native_expr if answer else None

        if not answer:
            llm_attempted = True
            logger.info("ChallengeSolver: Nativo fallo. Intentando extraer expresion con LLM y evaluar localmente...")
            answer = await self._extract_and_eval_with_llm(challenge_text)
            if answer:
                extracted_expr = self._last_extracted_expr

        if not answer:
            logger.info("ChallengeSolver: LLM+eval fallo. Intentando con LLM como respaldo...")
            answer = await self._solve_with_llm(challenge_text)
            if answer:
                extracted_expr = self._last_llm_raw

        if not answer:
            logger.warning("ChallengeSolver: No se pudo resolver el challenge (ni Python ni LLM).")
            _record_sample(extracted_expr, None, None, None, False)
            return False

        if not re.match(r"^-?\d+\.\d{2}$", str(answer).strip()):
            logger.warning(f"ChallengeSolver: respuesta no confiable o con formato invalido: {answer!r}")
            _record_sample(extracted_expr, str(answer), None, None, False)
            return False

        answer = str(answer).strip()
        logger.info(f"ChallengeSolver: Respuesta final '{answer}'. Enviando a Moltbook via submit_verification...")

        try:
            result = self.moltbook.submit_verification(verification_code, answer)

            if result and (result.get("success") or result.get("status") in (200, 201, 204)):
                logger.info("✅ ChallengeSolver: CAPTCHA resuelto y verificacion exitosa!")
                _record_sample(extracted_expr, answer, result.get("status"), None, True, result)
                return True
            else:
                logger.warning(f"ChallengeSolver: Moltbook rechazo la respuesta. Result: {result}")
                raw = result.get("raw") if isinstance(result, dict) else None
                server_message = None
                if isinstance(raw, dict):
                    server_message = raw.get("message") or raw.get("hint") or raw.get("error")
                _record_sample(
                    extracted_expr,
                    answer,
                    result.get("status") if isinstance(result, dict) else None,
                    server_message,
                    False,
                    result,
                )

                # ── Reintento UNICO asistido por LLM tras rechazo del servidor ──
                # Caso real (20/08/2026 20:09): el solver nativo extrajo una
                # expresion de 2 operandos y Moltbook la rechazo ("Incorrect
                # answer"), pero el flujo original terminaba sin consultar al
                # LLM porque nativo SI produjo respuesta. Un solo reintento:
                # evita martillar submit_verification con respuestas equivocadas.
                if not llm_attempted:
                    logger.info("ChallengeSolver: rechazo con respuesta nativa; reintento unico via LLM...")
                    llm_attempted = True
                    llm_answer = await self._extract_and_eval_with_llm(challenge_text)
                    llm_expr = self._last_extracted_expr
                    if not llm_answer:
                        llm_answer = await self._solve_with_llm(challenge_text)
                        llm_expr = self._last_llm_raw
                    retry_answer = str(llm_answer).strip() if llm_answer else ""
                    if retry_answer and re.match(r"^-?\d+\.\d{2}$", retry_answer) and retry_answer != answer:
                        try:
                            result2 = self.moltbook.submit_verification(verification_code, retry_answer)
                            if result2 and (result2.get("success") or result2.get("status") in (200, 201, 204)):
                                logger.info(
                                    "✅ ChallengeSolver: verificacion exitosa en reintento LLM (%s)!",
                                    retry_answer,
                                )
                                _record_sample(llm_expr, retry_answer, result2.get("status"), None, True, result2)
                                return True
                            _record_sample(
                                llm_expr,
                                retry_answer,
                                result2.get("status") if isinstance(result2, dict) else None,
                                None,
                                False,
                                result2,
                            )
                            logger.warning("ChallengeSolver: reintento LLM tambien rechazado; abandonando.")
                        except Exception as e2:
                            logger.error("ChallengeSolver: error en reintento LLM: %s", e2)
                            _record_sample(llm_expr, retry_answer, None, str(e2), False)
                    else:
                        logger.info(
                            "ChallengeSolver: LLM sin alternativa valida (respuesta=%r); se mantiene el fallo inicial.",
                            retry_answer or None,
                        )
                return False
        except Exception as e:
            logger.error(f"ChallengeSolver: Error al enviar respuesta a Moltbook: {e}")
            _record_sample(extracted_expr, answer, None, str(e), False)
            return False

    def _solve_native_math(self, text: str) -> Optional[str]:
        """Intenta resolver la matematica directamente con Python, sin usar el LLM."""
        try:
            if not text:
                return None

            current = self._fix_mojibake(text)
            normalized = self._normalize_math_text(current)

            match = re.search(r'(\d+\.?\d*)\s*([+\-*/])\s*(\d+\.?\d*)', normalized)
            if not match:
                return None

            num1 = float(match.group(1))
            op = match.group(2)
            num2 = float(match.group(3))
            self._last_native_expr = match.group(0)

            result = None
            if op == '+':
                result = num1 + num2
            elif op == '-':
                result = num1 - num2
            elif op == '*':
                result = num1 * num2
            elif op == '/' and num2 != 0:
                result = num1 / num2

            if result is not None:
                answer = f"{result:.2f}"
                logger.info(f"ChallengeSolver: Exito nativo! {num1} {op} {num2} = {answer}")
                return answer

        except Exception as e:
            logger.warning(f"ChallengeSolver: Error en _solve_native_math: {e}")
        return None


    async def _generate_with_captcha_fallback(self, prompt: str, system_prompt: str) -> str:
        """Extraccion de la expresion del CAPTCHA: gratis (classify) primero,
        tier_flash como ultimo recurso. Una expresion matematica no necesita un
        modelo de frontera; Anthropic queda fuera del camino de clasificacion."""
        for _tier in ["classify", "flash"]:
            try:
                response = await self.model_cascade.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=1024,
                    temperature=0.0,
                    tier=_tier
                )
                if response:
                    logger.info(f"ChallengeSolver: respuesta obtenida via tier={_tier}")
                    return response
            except Exception as _e:
                logger.warning(f"ChallengeSolver: tier={_tier} fallido: {_e}. Intentando siguiente...")
        raise Exception("Todos los tiers CAPTCHA fallaron (classify, flash)")

    async def _solve_with_llm(self, text: str) -> Optional[str]:
        if not self.model_cascade:
            logger.error("ChallengeSolver: ModelCascade no disponible.")
            return None

        # BUG FIX: Ya no borramos los operadores matematicos ni los decimales
        prompt = (
            "You are a math solver. The following text contains a math problem written in "
            "obfuscated mixed case with random symbols. Decode it, extract the numbers and "
            "operation, solve it, and reply ONLY with the final numerical answer to exactly "
            "2 decimal places. No explanations, no units, no text. Example: 42.00\n\n"
            f"Text: {text}\n\n"
            "Final numerical answer (digits and dot only):"
        )

        try:
            response = await self._generate_with_captcha_fallback(
                prompt=prompt,
                system_prompt="You output ONLY numbers. No text. Reply with just the decimal number."
            )
            self._last_llm_raw = response
            numbers = re.findall(r"-?\d+\.?\d*", response)
            if numbers:
                try:
                    return f"{float(numbers[-1]):.2f}"
                except ValueError:
                    return numbers[-1]
            return response.strip()
        except Exception as e:
            logger.error(f"ChallengeSolver: Error llamando al LLM: {e}")
            return None













