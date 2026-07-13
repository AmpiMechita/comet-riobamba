import ast
import re
from services.captcha_math_solver import solve_captcha_math
# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("services.challenge_solver")

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

    async def solve_and_verify(self, challenge_data: Dict[str, Any]) -> bool:
        verification_code = challenge_data.get("verification_code")
        challenge_text = challenge_data.get("challenge_text", "")

        if not challenge_text or not verification_code:
            logger.warning("ChallengeSolver: datos incompletos.")
            return False

        logger.info("ChallengeSolver: Intentando resolver CAPTCHA nativamente con Python...")
        answer = solve_captcha_math(challenge_text) or self._solve_native_math(challenge_text)

        if not answer:
            logger.info("ChallengeSolver: Nativo fallo. Intentando extraer expresion con LLM y evaluar localmente...")
            answer = await self._extract_and_eval_with_llm(challenge_text)

        if not answer:
            logger.info("ChallengeSolver: LLM+eval fallo. Intentando con LLM como respaldo...")
            answer = await self._solve_with_llm(challenge_text)

        if not answer:
            logger.warning("ChallengeSolver: No se pudo resolver el challenge (ni Python ni LLM).")
            return False

        if not re.match(r"^-?\d+\.\d{2}$", str(answer).strip()):
            logger.warning(f"ChallengeSolver: respuesta no confiable o con formato invalido: {answer!r}")
            return False

        answer = str(answer).strip()
        logger.info(f"ChallengeSolver: Respuesta final '{answer}'. Enviando a Moltbook via submit_verification...")

        try:
            result = self.moltbook.submit_verification(verification_code, answer)

            if result and (result.get("success") or result.get("status") in (200, 201, 204)):
                logger.info("✅ ChallengeSolver: CAPTCHA resuelto y verificacion exitosa!")
                return True
            else:
                logger.warning(f"ChallengeSolver: Moltbook rechazo la respuesta. Result: {result}")
                return False
        except Exception as e:
            logger.error(f"ChallengeSolver: Error al enviar respuesta a Moltbook: {e}")
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
        """Intenta premium (Anthropic) primero, luego cerebras si falla."""
        for _tier in ["premium", "cerebras"]:
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
        raise Exception("Todos los tiers CAPTCHA fallaron (premium, cerebras)")

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













