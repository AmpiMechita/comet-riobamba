import re
from decimal import Decimal, getcontext, InvalidOperation

getcontext().prec = 28

CAPTCHA_NUMBER_RE = re.compile(r"^-?\d+\.\d{2}$")

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
    expr = extract_math_expression(text)
    if not expr:
        return None

    result = evaluate_expression(expr)
    if result is None:
        return None

    return format_captcha_answer(result)
