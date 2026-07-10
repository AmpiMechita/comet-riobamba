"""
Solver de verification challenges de Moltbook.
El challenge_text viene ofuscado con símbolos (^, [, ], -, /) y capitalización alterna.
Debemos extraer el problema matemático y resolverlo devolviendo float con 2 decimales.
"""
import asyncio
import logging
import re
from typing import Optional

from services.captcha_math_solver import solve_captcha_math

logger = logging.getLogger(__name__)


class LLMClientAdapter:
    def __init__(self, cascade):
        self._mc = cascade

    async def complete(self, prompt, max_tokens=100, temperature=0.0):
        return await self._mc.generate(
            prompt=prompt, max_tokens=max_tokens, temperature=temperature,
        )


# ── Word-to-number mapping for obfuscated challenges ────────────

WORD_TO_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

# Operation keywords found in Moltbook challenge text
OP_KEYWORDS = {
    "plus": "+", "add": "+", "adds": "+", "accelerate": "+", "accelerates": "+",
    "gains": "+", "speeds": "+", "increases": "+", "and": "+",
    "minus": "-", "subtract": "-", "slows": "-", "loses": "-",
    "decreases": "-", "drops": "-",
    "times": "*", "multiplied": "*", "multiply": "*",
    "divided": "/", "over": "/",
}


def _deobfuscate(text: str) -> str:
    """Remove obfuscation symbols and normalize alternating caps."""
    if not text:
        return ""
    # Strip obfuscation characters: ^ [ ] / (but keep - only between words)
    cleaned = re.sub(r'[\^\[\]/]', '', text)
    # Normalize to lowercase
    cleaned = cleaned.lower()
    # Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Remove stray dashes not part of negative numbers
    cleaned = re.sub(r'(?<!\d)-(?!\d)', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def _words_to_number(words: list[str], start: int) -> tuple[Optional[float], int]:
    """
    Parse a number from word tokens starting at `start`.
    Returns (number, next_index) or (None, start) if no number found.
    """
    if start >= len(words):
        return None, start

    # Try direct numeric literal first
    try:
        val = float(words[start])
        return val, start + 1
    except (ValueError, IndexError):
        pass

    total = 0.0
    current = 0.0
    found_any = False
    i = start

    while i < len(words):
        w = words[i]
        # Handle compound words like "twenty-three" (already split by deobfuscate)
        # Also handle "twen tyy" → fuzzy match
        matched = False
        for word_key, val in WORD_TO_NUM.items():
            if w == word_key or (len(w) > 3 and _fuzzy_match(w, word_key)):
                if val == 100:
                    current = (current or 1) * 100
                elif val >= 20:
                    current += val
                else:
                    current += val
                found_any = True
                matched = True
                i += 1
                break

        if not matched:
            break

    if found_any:
        total += current
        return total, i
    return None, start


def _fuzzy_match(candidate: str, target: str) -> bool:
    """Simple fuzzy match: candidate contains most of target's characters in order."""
    if not candidate or not target:
        return False
    # Remove doubled letters from candidate for comparison
    simplified = re.sub(r'(.)\1+', r'\1', candidate)
    target_simplified = re.sub(r'(.)\1+', r'\1', target)
    # Check if they're similar enough
    if simplified == target_simplified:
        return True
    # Levenshtein-lite: if candidate starts with target prefix (>60% match)
    min_len = min(len(simplified), len(target_simplified))
    if min_len < 3:
        return False
    matches = sum(1 for a, b in zip(simplified, target_simplified) if a == b)
    return matches / max(len(simplified), len(target_simplified)) > 0.7


def _solve_from_words(text: str) -> Optional[str]:
    """
    Try to solve a challenge by parsing number-words and operation keywords.
    Example: "a lobster swims at twenty meters and slows by five" → 20 - 5 = 15.00
    """
    cleaned = _deobfuscate(text)
    words = cleaned.split()

    # First, try to find a direct numeric expression in the deobfuscated text
    native_result = solve_captcha_math(cleaned)
    if native_result:
        return native_result

    # Parse word-based math
    numbers = []
    operators = []
    i = 0

    while i < len(words):
        # Try to parse a number
        num, next_i = _words_to_number(words, i)
        if num is not None:
            numbers.append(num)
            i = next_i
            continue

        # Try to parse an operator
        w = words[i]
        if w in OP_KEYWORDS:
            operators.append(OP_KEYWORDS[w])
            i += 1
            continue

        # Check "by" followed by a number (common pattern: "slows by five")
        if w == "by" and i + 1 < len(words):
            i += 1
            continue

        i += 1

    # Need at least 2 numbers and 1 operator
    if len(numbers) >= 2 and len(operators) >= 1:
        result = numbers[0]
        for idx, op in enumerate(operators):
            if idx + 1 >= len(numbers):
                break
            n = numbers[idx + 1]
            if op == "+":
                result += n
            elif op == "-":
                result -= n
            elif op == "*":
                result *= n
            elif op == "/" and n != 0:
                result /= n
            else:
                return None
        return f"{result:.2f}"

    return None


def solve_sync(challenge_text: str, llm_client) -> Optional[str]:
    """Synchronous wrapper for the async solve function."""
    logger.info(f"[CHALLENGE_SOLVER] Raw challenge_text: {challenge_text!r}")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                asyncio.wait_for(solve(challenge_text, llm_client), timeout=15)
            )
        finally:
            loop.close()
    except asyncio.TimeoutError:
        logger.error("[CHALLENGE_SOLVER] solve_sync TIMEOUT after 15s")
        return None
    except Exception as e:
        logger.error(f"[CHALLENGE_SOLVER] solve_sync FAIL: {e}")
        return None


# LLM prompt — English, clear instructions
SOLVER_PROMPT = """You are a math puzzle solver. The following text is an obfuscated math challenge with random symbols (^ [ ] / -) and alternating capitalization mixed in. Your task:
1. Ignore ALL symbols: ^ [ ] / - and the alternating caps
2. Read the clean text and identify the math problem (numbers may be written as words)
3. Solve the arithmetic operation (addition, subtraction, multiplication, or division)
4. Reply with ONLY the numerical answer formatted to exactly 2 decimal places (e.g. 15.00)

NO explanations, NO units, NO text — just the number.

Obfuscated text: {challenge_text}
Answer:"""


async def solve(challenge_text: str, llm_client) -> Optional[str]:
    """
    Resuelve un challenge matemático ofuscado.
    Strategy: native parse → word-based parse → LLM fallback.
    Devuelve el answer como string "15.00" o None si falla.
    """
    if not challenge_text:
        return None

    # ── Step 1: Try native regex extraction on raw text ──
    native = solve_captcha_math(challenge_text)
    if native:
        logger.info(f"[CHALLENGE_SOLVER] Solved natively: {native}")
        return native

    # ── Step 2: Deobfuscate and try word-based parsing ──
    word_result = _solve_from_words(challenge_text)
    if word_result:
        logger.info(f"[CHALLENGE_SOLVER] Solved from word parsing: {word_result}")
        return word_result

    # ── Step 3: LLM fallback ──
    if not llm_client:
        logger.error("[CHALLENGE_SOLVER] No llm_client available, cannot solve")
        return None

    try:
        prompt = SOLVER_PROMPT.format(challenge_text=challenge_text)
        raw = await llm_client.complete(prompt, max_tokens=100, temperature=0.0)
        raw = (raw or "").strip()
        logger.info(f"[CHALLENGE_SOLVER] LLM raw response: {raw!r}")

        # Extract the first number from the response
        numbers = re.findall(r"-?\d+\.?\d*", raw)
        if numbers:
            value = float(numbers[0])
            answer = f"{value:.2f}"
            logger.info(f"[CHALLENGE_SOLVER] LLM solved: challenge='{challenge_text[:60]}...' answer={answer}")
            return answer

        # Try to parse the whole response as a number
        value = float(raw)
        answer = f"{value:.2f}"
        logger.info(f"[CHALLENGE_SOLVER] LLM solved (direct): answer={answer}")
        return answer

    except (ValueError, TypeError) as e:
        logger.error(f"[CHALLENGE_SOLVER] FAIL parse answer from LLM: '{raw}' error={e}")
        return None
    except Exception as e:
        logger.error(f"[CHALLENGE_SOLVER] FAIL unexpected: {e}")
        return None
