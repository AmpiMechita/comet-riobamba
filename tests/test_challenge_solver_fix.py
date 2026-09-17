"""Tests para el fix del challenge solver (2026-09-16)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.challenge_solver import ChallengeSolver


class TestLooksObfuscated:
    def test_obfuscated_with_brackets(self):
        assert ChallengeSolver._looks_obfuscated("3^8 + 1[5]") is True

    def test_obfuscated_with_mixed_caps(self):
        text = "ThReE pLuS fIvE"
        assert ChallengeSolver._looks_obfuscated(text) is True

    def test_clean_text_not_obfuscated(self):
        assert ChallengeSolver._looks_obfuscated("3 + 5") is False

    def test_empty_text(self):
        assert ChallengeSolver._looks_obfuscated("") is False


class TestSolverFlow:
    @pytest.mark.asyncio
    async def test_llm_used_first_when_available(self):
        """LLM se usa primero. Nativo no se invoca."""
        solver = ChallengeSolver.__new__(ChallengeSolver)
        solver.moltbook = MagicMock()
        solver.moltbook.submit_verification = MagicMock(return_value={"success": True, "status": 200})
        solver._last_extracted_expr = "15+23"
        solver._last_native_expr = None
        solver._last_llm_raw = None
        solver.model_cascade = MagicMock()

        with patch.object(solver, "_extract_and_eval_with_llm", new=AsyncMock(return_value="38.00")), \
             patch("services.challenge_solver.solve_captcha_math") as mock_native:
            result = await solver.solve_and_verify({
                "challenge_text": "What is 15 + 23?",
                "verification_code": "verification_code"
            })
            assert result is True
            mock_native.assert_not_called()
            solver.moltbook.submit_verification.assert_called_once_with("verification_code", "38.00")

    @pytest.mark.asyncio
    async def test_single_submit_no_retry(self):
        """Aunque el submit devuelva 400, se llama UNA vez."""
        solver = ChallengeSolver.__new__(ChallengeSolver)
        solver.moltbook = MagicMock()
        solver.moltbook.submit_verification = MagicMock(return_value={"success": False, "status": 400})
        solver._last_extracted_expr = "15+23"
        solver._last_native_expr = None
        solver._last_llm_raw = None
        solver.model_cascade = MagicMock()

        with patch.object(solver, "_extract_and_eval_with_llm", new=AsyncMock(return_value="38.00")):
            result = await solver.solve_and_verify({
                "challenge_text": "What is 15 + 23?",
                "verification_code": "verification_code"
            })
            assert result is False
            assert solver.moltbook.submit_verification.call_count == 1

    @pytest.mark.asyncio
    async def test_obfuscated_skips_native_fallback(self):
        """Si LLM falla y el texto está ofuscado, no intenta nativo."""
        solver = ChallengeSolver.__new__(ChallengeSolver)
        solver.moltbook = MagicMock()
        solver._last_extracted_expr = None
        solver._last_native_expr = None
        solver._last_llm_raw = None
        solver.model_cascade = MagicMock()

        with patch.object(solver, "_extract_and_eval_with_llm", new=AsyncMock(return_value=None)), \
             patch("services.challenge_solver.solve_captcha_math") as mock_native:
            result = await solver.solve_and_verify({
                "challenge_text": "3^8 + 1[5]",
                "verification_code": "verification_code"
            })
            assert result is False
            mock_native.assert_not_called()


class TestPromptReinforced:
    """Verifica que el prompt incluye ejemplos de desofuscacion (2026-09-16)."""

    def test_prompt_contains_obfuscation_warning(self):
        import inspect
        from services import challenge_solver
        src = inspect.getsource(challenge_solver.ChallengeSolver._extract_and_eval_with_llm)
        assert "OBFUSCATED" in src
        assert "noise characters" in src

    def test_prompt_contains_number_examples(self):
        import inspect
        from services import challenge_solver
        src = inspect.getsource(challenge_solver.ChallengeSolver._extract_and_eval_with_llm)
        assert "twenty seven" in src
        assert "thirty two" in src
        assert "fourteen" in src

    def test_prompt_mentions_noise_chars(self):
        import inspect
        from services import challenge_solver
        src = inspect.getsource(challenge_solver.ChallengeSolver._extract_and_eval_with_llm)
        assert "[ ] ^ ~" in src

    def test_pro_tier_in_fallback(self):
        import inspect
        from services import challenge_solver
        src = inspect.getsource(challenge_solver.ChallengeSolver._generate_with_captcha_fallback)
        marker = chr(34) + "pro" + chr(34)
        assert marker in src, "tier pro debe estar en el fallback"