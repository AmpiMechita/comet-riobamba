"""Tests for services/challenge_solver.py — critical path with zero prior coverage."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from services.challenge_solver import ChallengeSolver


@pytest.fixture(autouse=True)
def _isolate_captcha_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.challenge_solver._CAPTCHA_SAMPLES_PATH",
        tmp_path / "captcha_samples.jsonl",
    )


# ── Native math solving ──────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("What is 12 + 34?", "46.00"),
    ("Solve: 100 - 25", "75.00"),
    ("Calculate 8 × 7", "56.00"),
    ("Divide 144 ÷ 12", "12.00"),
    ("Compute 5 * 3", "15.00"),
])
def test_solve_native_math_basic(text, expected):
    solver = ChallengeSolver(MagicMock())
    assert solver._solve_native_math(text) == expected


def test_solve_native_math_decimal():
    solver = ChallengeSolver(MagicMock())
    assert solver._solve_native_math("3.5 + 2.5") == "6.00"


def test_solve_native_math_division_by_zero():
    solver = ChallengeSolver(MagicMock())
    result = solver._solve_native_math("10 / 0")
    assert result is None


def test_solve_native_math_no_operation():
    solver = ChallengeSolver(MagicMock())
    result = solver._solve_native_math("hello world")
    assert result is None


def test_solve_native_math_empty_text():
    solver = ChallengeSolver(MagicMock())
    assert solver._solve_native_math("") is None
    assert solver._solve_native_math(None) is None


# ── Safe eval expression ─────────────────────────────────────────


@pytest.mark.parametrize("expr,expected", [
    ("23 * 7", 161.0),
    ("23+7", 30.0),
    ("100 - 25", 75.0),
    ("8 * 7", 56.0),
    ("144 / 12", 12.0),
    ("3.5 + 2.5", 6.0),
    ("23*7", 161.0),            # no whitespace
    ("  23   *   7  ", 161.0),   # extra whitespace
    ("23* 7", 161.0),            # inconsistent whitespace
    (" -5 + 3", -2.0),           # unary minus
])
def test_safe_eval_valid_arithmetic(expr, expected):
    assert ChallengeSolver._safe_eval_expression(expr) == expected


@pytest.mark.parametrize("expr", [
    "",
    "abc",
    "__import__('os').system('ls')",
    "globals()",
    "locals()",
    "open('/etc/passwd')",
    "1; import os",
    "exec('x=1')",
    "lambda: 1",
    "[]",
    "{}",
])
def test_safe_eval_rejects_unsafe(expr):
    assert ChallengeSolver._safe_eval_expression(expr) is None


# ── Mojibake fixing ──────────────────────────────────────────────


def test_fix_mojibake_clean_text():
    solver = ChallengeSolver(MagicMock())
    text = "Hello world"
    assert solver._fix_mojibake(text) == text


def test_fix_mojibake_empty():
    solver = ChallengeSolver(MagicMock())
    assert solver._fix_mojibake("") == ""
    assert solver._fix_mojibake(None) is None


# ── Solve and verify ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_solve_and_verify_incomplete_data():
    solver = ChallengeSolver(MagicMock())
    assert await solver.solve_and_verify({}) is False
    assert await solver.solve_and_verify({"verification_code": "abc"}) is False
    assert await solver.solve_and_verify({"challenge_text": "2+2"}) is False


@pytest.mark.asyncio
async def test_solve_and_verify_native_success():
    mock_api = MagicMock()
    mock_api.submit_verification.return_value = {"success": True, "status": 200}
    solver = ChallengeSolver(mock_api)

    result = await solver.solve_and_verify({
        "verification_code": "v123",
        "challenge_text": "What is 12 + 34?",
    })
    assert result is True
    mock_api.submit_verification.assert_called_once_with("v123", "46.00")


@pytest.mark.asyncio
async def test_solve_and_verify_native_failure_api_rejects():
    mock_api = MagicMock()
    mock_api.submit_verification.return_value = {"success": False, "status": 400}
    solver = ChallengeSolver(mock_api)

    result = await solver.solve_and_verify({
        "verification_code": "v123",
        "challenge_text": "What is 1 + 1?",
    })
    assert result is False


# ── LLM fallback ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_fallback_when_native_fails():
    mock_api = MagicMock()
    mock_api.submit_verification.return_value = {"success": True, "status": 200}
    mock_cascade = AsyncMock()
    mock_cascade.generate.return_value = "42.00"

    solver = ChallengeSolver(mock_api, model_cascade=mock_cascade)

    # Text without recognizable operation forces LLM fallback
    result = await solver.solve_and_verify({
        "verification_code": "v999",
        "challenge_text": "unrecognized riddle text with no numbers",
    })
    assert result is True
    assert mock_cascade.generate.called


@pytest.mark.asyncio
async def test_llm_fallback_no_model_cascade():
    mock_api = MagicMock()
    solver = ChallengeSolver(mock_api, model_cascade=None)

    result = await solver._solve_with_llm("some text")
    assert result is None


@pytest.mark.asyncio
async def test_llm_fallback_parses_response():
    mock_cascade = AsyncMock()
    mock_cascade.generate.return_value = "The answer is 99.99"
    solver = ChallengeSolver(MagicMock(), model_cascade=mock_cascade)

    result = await solver._solve_with_llm("some math problem")
    assert result == "99.99"


# ── Invalid answer format ────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_answer_format_rejected():
    mock_api = MagicMock()
    mock_cascade = AsyncMock()
    mock_cascade.generate.return_value = "not a number"

    solver = ChallengeSolver(mock_api, model_cascade=mock_cascade)

    result = await solver.solve_and_verify({
        "verification_code": "v555",
        "challenge_text": "something obscure",
    })
    assert result is False


# ── Tests for core.challenge_solver (function-based solver) ──────


class MockLLM:
    def __init__(self, response):
        self.response = response
    async def complete(self, prompt, **kwargs):
        return self.response


@pytest.mark.asyncio
async def test_core_simple_subtraction():
    from core.challenge_solver import solve
    llm = MockLLM("15.00")
    result = await solve("A] lO^bSt-Er S[wImS aT/ tW]eNn-Tyy mE^tE[rS aNd] SlO/wS bY^ fIve", llm)
    assert result == "15.00"


@pytest.mark.asyncio
async def test_core_integer_result_formatted():
    from core.challenge_solver import solve
    llm = MockLLM("42")
    result = await solve("some challenge", llm)
    assert result == "42.00"


@pytest.mark.asyncio
async def test_core_invalid_llm_response_returns_none():
    from core.challenge_solver import solve
    llm = MockLLM("no sé")
    result = await solve("some challenge", llm)
    assert result is None


@pytest.mark.asyncio
async def test_core_negative_result():
    from core.challenge_solver import solve
    llm = MockLLM("-3.50")
    result = await solve("some challenge", llm)
    assert result == "-3.50"


@pytest.mark.asyncio
async def test_core_decimal_precision():
    from core.challenge_solver import solve
    llm = MockLLM("7.5")
    result = await solve("some challenge", llm)
    assert result == "7.50"


@pytest.mark.parametrize("challenge_text,expected", [
    ("A] LoObSsT.eR] ClAw^ FoRcE] Is^ ThIrTy] FiVe} NeUwToNs, Um| AnD] tHe] OtHeR^ ClAw~ AdDs] TwEnTy} FoUr< NeUwToNs, WhAt'S] ThE^ ToTaL| FoRcE?", "59.00"),
    ("A] L oO b- StEr ] C lA w ] E xE rT s^ T hI rTy ] nOoToNs ] aNd ] tHe ] rIvA l ] cLaW ] A dD s ] T wE lV e ] nOoToNs , ] wHaT ] iS ] tHe ] tO tA l ] fOrCe ? ~ < > |", "42.00"),
    ("ThIs] lO.oB sT-Er LooobsssTeR^ ExErTs TwEnTy ThReE nootons ] - [ DuRiNg MoLtInG It LoSeS SeVeN nootons, Um~ WhAt Is ThE NeT FoRcE< ? ", "16.00"),
    ("A] LoObBsS tErR sW^iMmS uMm/ iN tHe] aQuA lIkE, lOoObBsSsTeR vElAwCiTeE iS tW/eN tY tHrEe MeTeRs- PeR sEeCoNd, aNd| iTs ClAaWw FoOrRcEe Is F/oUr NeWToNs~ MuLtI^pLy ThEsE, hOw MaNy NooOtOnMeTeR sIsSs?", "92.00"),
    ("A] Lo.BsT-Er] ClAw ^FoRcE Is ThIrTy TwO NeW<ToNs Um, AnD InCrEaSeS By FiFfTeEn NeW>ToNs, WhAt Is ThE ToTaL FoRcE?", "47.00"),
    ("A] lO oBbSsTt-Er' s ClA^w ExE rTs ThIrTy FiVeee NooToNs ] AnD T]hE W~aTeR PrE ssUrE AdDs TwElVe NooToNs, WhAt'S ToTaL FoRcE?", "47.00"),
    ("A] lO^bSt-Er LoOobsssTeR cLaW fO^rCe Is S[iRrTy FivE] nEu-TonSs- ]+ [aNoThEr] lOoObsTtEr ClAw fOrCe Is T[wElVe] nEu-TonSs, WhAt Is ToTaL FOrCe?", "47.00"),
    ("A] Lo.oBbS tErRr ~ S^wImS| aT/ tWeNtY tHrEe <vElAwCiTeE> ]cM/s AnD- AcCeLeRaTeS{ bY/ sEvEn }uMn, WhAtS- ThE^ nEw| VeLo^oCiTy?", "30.00"),
    ("EaCh ] lO-oObBsTtErr ] ClAw ] FoRcE ] iS ] tHiRrTy^ fIiV[e ] NoOtT/OnS umm, AnD ] tW/oO ] lOoObBsStTeRrS ] piN]cH, HoW ] mUcH ] ToTaL ] FoR/ce ] (uSe ] mUlTiPlY) ?", "70.00"),
    ("A] lO.bSt-Er S^wImS lIke V eL aWcItEe At] tWeN tY ThReE cE nTiMeTeRs/ pEr SeCoNd, uM| dU rInG a D oMmInAnCe] fIgH t It LoSeS sEvEn, wHaT]s N eW vE lO cItY ~?", "16.00"),
    ("A] L oO b- StE rr ClA w] ExE rTs^ ThIr Ty FiV e] NoOt-O nS ~ AnD/ WaTe R] PrEs SuRe- AdD s^ SeV eN {,} WhA tIs/ ToTa L?", "42.00"),
    ("A] Lo.O bS tEr'S SwImMiNnG VeLaWcItEe Is] TwEnTy ThReE MeTeRs PeR MiNuTe, AnD A CuRrReEnT AdDs FiVe MeTeRs PeR MiNuTe; WhAt'S CoMbInEd VeLoCiTy? ^ { < > }", "28.00"),
    ("A] lOoObSsTtEeR] 'Ss ClLaW^ aPpLlIiEs/ tHhIiRrTtYy TwWoO nEeWwToOnNs- aNd] aNnOtThHeR^ aPpPlIiEeS/ eIiGhHtTeEeN nEeWwToOnNs, wHaT/ iSs] tHe^ ToOtTaLl FoOrRcEe?", "50.00"),
    ("A] lOo-BsTtErRr S^cLaWw F|oRrCeE iSs [fO rTy] fIi-Ve~ nEu-TooNs\\, uM {mOlTtInG} aDdS/ tWe-LvE, hOw^ mAnY] nEeW| fO rCeE< tOtAl>?", "57.00"),
])
def test_production_obfuscated_samples(challenge_text, expected):
    from services.captcha_math_solver import solve_captcha_math
    assert solve_captcha_math(challenge_text) == expected

