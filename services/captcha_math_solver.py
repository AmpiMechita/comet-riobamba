import re
from decimal import Decimal, getcontext, InvalidOperation

getcontext().prec = 28

CAPTCHA_NUMBER_RE = re.compile(r"^-?\d+\.\d{2}$")

import re
from decimal import Decimal, getcontext, InvalidOperation

getcontext().prec = 28

CAPTCHA_NUMBER_RE = re.compile(r"^-?\d+\.\d{2}$")

NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100
}

def _collapse_repeated(s: str) -> str:
    res = []
    for c in s:
        if not res or res[-1] != c:
            res.append(c)
    return "".join(res)

def _fuzzy_match_number_word(cand: str):
    if cand in NUM_WORDS:
        return cand, NUM_WORDS[cand]
    c = _collapse_repeated(cand)
    if c in NUM_WORDS:
        return c, NUM_WORDS[c]

    # Common OCR/noise variations
    if c in ("eighten", "eightn"):
        return "eighteen", 18
    if c in ("fiv", "fiiv", "fiff"):
        return "five", 5
    if c in ("fiften", "fiffteen"):
        return "fifteen", 15
    if c in ("srrty", "sirty", "sirrty", "shirty"):
        return "thirty", 30
    if c in ("forth", "fourty", "forti"):
        return "forty", 40
    if c in ("tvelve", "twelv", "twelvee"):
        return "twelve", 12
    if c in ("sevn", "seveen"):
        return "seven", 7
    if c in ("twentee", "twenti"):
        return "twenty", 20
    if c in ("too", "tuve"):
        return "two", 2
    if c in ("thre", "thrrr"):
        return "three", 3

    return None, None

def _extract_numbers_from_text(text: str):
    clean = re.sub(r"[\[\]\{\}\^\~\|\<\>\\\/._\-*+,'\";:=?()!]", " ", text).lower()
    raw_tokens = clean.split()

    found_numbers = []
    n = len(raw_tokens)
    i = 0
    while i < n:
        matched = False
        for length in range(4, 0, -1):
            if i + length <= n:
                joined = "".join(raw_tokens[i:i+length])
                w, val = _fuzzy_match_number_word(joined)
                if val is not None:
                    found_numbers.append((i, i+length, val, w))
                    i += length
                    matched = True
                    break
        if not matched:
            if re.fullmatch(r"\d+(?:\.\d+)?", raw_tokens[i]):
                val = float(raw_tokens[i])
                found_numbers.append((i, i+1, val, raw_tokens[i]))
            i += 1

    merged = []
    j = 0
    while j < len(found_numbers):
        start_idx, end_idx, val, w = found_numbers[j]
        if j + 1 < len(found_numbers):
            next_start, next_end, next_val, next_w = found_numbers[j+1]
            if next_start <= end_idx + 1:
                if val in [20, 30, 40, 50, 60, 70, 80, 90] and next_val in range(1, 10):
                    merged.append(val + next_val)
                    j += 2
                    continue
        merged.append(val)
        j += 1

    return merged

def _detect_operation(text: str):
    clean = re.sub(r"[\[\]\{\}\^\~\|\<\>\\\/._\-*+,'\";:=?()!]", " ", text).lower()
    compact = re.sub(r"[^a-z]", "", clean)

    if any(k in compact for k in ["multi", "times", "product"]):
        return "*"

    if any(k in compact for k in ["lose", "lost", "losing", "drop", "decreas", "minus", "slow", "subtr"]):
        return "-"

    if any(k in compact for k in ["divid", "quotient"]):
        return "/"

    return "+"

def extract_math_expression(text: str) -> str | None:
    if not text or not isinstance(text, str):
        return None

    text = text.replace("\u00d7", "*").replace("\u00f7", "/").replace("\u2212", "-")

    pattern = re.compile(r"(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)")
    match = pattern.search(text)
    if not match:
        return None

    return match.group(0)

def evaluate_expression(expr: str) -> Decimal | None:
    if not expr:
        return None

    pattern = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*$")
    m = pattern.match(expr)
    if not m:
        return None

    left_str, op, right_str = m.groups()

    try:
        left = Decimal(left_str)
        right = Decimal(right_str)
    except InvalidOperation:
        return None

    try:
        if op == "+":
            result = left + right
        elif op == "-":
            result = left - right
        elif op == "*":
            result = left * right
        elif op == "/":
            if right == 0:
                return None
            result = left / right
        else:
            return None
    except Exception:
        return None

    return result

def format_captcha_answer(value: Decimal) -> str | None:
    if value is None:
        return None

    try:
        quantized = value.quantize(Decimal("0.00"))
    except InvalidOperation:
        return None

    answer = f"{quantized:.2f}"

    if not CAPTCHA_NUMBER_RE.match(answer):
        return None

    return answer

def solve_captcha_math(text: str) -> str | None:
    if not text or not isinstance(text, str):
        return None

    # 1. Intentar expresion matematica literal primero ("12 + 34", "8 * 7")
    expr = extract_math_expression(text)
    if expr:
        result = evaluate_expression(expr)
        if result is not None:
            formatted = format_captcha_answer(result)
            if formatted:
                return formatted

    # 2. Desofuscacion de problema en texto ("thirty five newtons and twelve newtons")
    nums = _extract_numbers_from_text(text)
    if len(nums) < 2:
        return None

    op = _detect_operation(text)
    n1, n2 = nums[0], nums[1]

    try:
        d1 = Decimal(str(n1))
        d2 = Decimal(str(n2))
        if op == "+":
            res = d1 + d2
        elif op == "-":
            res = d1 - d2
        elif op == "*":
            res = d1 * d2
        elif op == "/":
            if d2 == 0:
                return None
            res = d1 / d2
        else:
            return None
        return format_captcha_answer(res)
    except (InvalidOperation, Exception):
        return None

