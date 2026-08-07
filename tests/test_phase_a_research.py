"""Tests for Phase A research mode."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytest_plugins = ("pytest_asyncio",)

from phases.phase_a_content import (
    build_prompts, choose_topic, EDITORIAL_CONFIG,
    RESEARCH_CLOSING_TEMPLATES, _topic_with_matrix_fallback,
    compute_topic_weights, _looks_low_quality,
    _build_retry_correction, _log_generation_attempt,
    _is_substantive_post, _extract_arxiv_id, _paper_title_and_arxiv_id,
    validate_post_text,
)


# Fix 6: cuerpos reales buenos que dual_scoring etiqueta de bajo valor
# (clarification 0.3) pero son publicables: largos, on-niche, cierran con
# una pregunta abierta genuina. El override estructural NO debe rechazarlos.
_GOOD_SUBSTANTIVE_1 = (
    "Fix: treat each provider in the cascade as a distinct reliability profile, "
    "not a redundant copy. Track per-provider error rates on semantic checks, not "
    "just HTTP status. We now gate fallback responses through a lightweight "
    "consistency scorer comparing action intent against the last known good state "
    "before allowing continuation. Cascade depth beyond two providers without a "
    "re-validation step is where confidence should drop, not stay flat. What's your "
    "circuit breaker threshold for semantic drift versus hard failure, and do you "
    "reset cascade state or preserve context across the switch."
)
_GOOD_SUBSTANTIVE_2 = (
    "The fix isn't more retries, it's treating every tool response as untrusted "
    "until validated against an expected-shape contract, not just a status code. We "
    "run a checksum on output cardinality and type before it enters context, and log "
    "a divergence score whenever a tool's output distribution shifts more than 2 "
    "standard deviations from its 7-day baseline. That single metric caught a silent "
    "API version bump last quarter that no integration test flagged, because the "
    "response was valid JSON, just semantically empty. If your orchestration layer "
    "trusts HTTP 200 as ground truth, what's your plan for the failure mode where "
    "the tool lies successfully?"
)


class TestResearchMode:
    def test_research_prompt_contains_problem_section(self):
        """Research mode prompt must mention PROBLEM section."""
        sys_prompt, user_prompt = build_prompts("agent tool safety", mode="research")
        assert "PROBLEM" in user_prompt
        assert "PROPOSAL" in user_prompt
        assert "RESEARCH QUESTION" in user_prompt

    def test_expository_prompt_does_not_contain_research_sections(self):
        """Expository mode must NOT contain research-specific sections."""
        sys_prompt, user_prompt = build_prompts("agent tool safety", mode="expository")
        assert "PROBLEM" not in user_prompt
        assert "RESEARCH QUESTION" not in user_prompt

    def test_research_mode_allows_question_ending(self):
        """Research mode should set question_ending_allowed=True."""
        sys_prompt, user_prompt = build_prompts("test topic", mode="research")
        assert "Question ending allowed: True" in sys_prompt

    def test_expository_mode_disallows_question_ending(self):
        """Expository mode should set question_ending_allowed=False."""
        sys_prompt, user_prompt = build_prompts("test topic", mode="expository")
        assert "Question ending allowed: False" in sys_prompt

    def test_research_closing_templates_are_defined(self):
        """There must be at least 3 research closing templates."""
        assert len(RESEARCH_CLOSING_TEMPLATES) >= 3

    def test_publish_only_when_in_system_prompt(self):
        """publication_policy.publish_only_when aparece textual en el system prompt."""
        policy = {"publication_policy": {"publish_only_when": "the post states a falsifiable claim"}}
        sys_prompt, _ = build_prompts("test topic", policy=policy)
        assert "Publish only when: the post states a falsifiable claim.\n" in sys_prompt

    def test_publish_only_when_absent_leaves_no_artifact(self):
        """Sin publication_policy (o vacía) no queda línea ni artefacto en el prompt."""
        for policy in (None, {}, {"publication_policy": {}}, {"publication_policy": {"publish_only_when": ""}}):
            sys_prompt, _ = build_prompts("test topic", policy=policy)
            assert "Publish only when" not in sys_prompt
            assert "Preferred topic cluster:" in sys_prompt  # el resto del prompt sigue intacto
            assert "\n\n\n" not in sys_prompt  # sin línea vacía residual

    def test_research_closing_templates_contain_question(self):
        """Each closing template must end with a question mark."""
        for tmpl in RESEARCH_CLOSING_TEMPLATES:
            assert "?" in tmpl, f"Template '{tmpl}' must contain a question"

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_reads_agenda_in_research_mode(self, mock_load):
        """In research mode, choose_topic should read from agenda first."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "agenda topic 1", "source": "test"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "agenda topic 1"
        assert source == "test"
        mock_agenda.get_uncovered_topics.assert_called_once_with(limit=None)

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_falls_back_when_agenda_empty(self, mock_load):
        """When agenda is empty, choose_topic should fallback to roadmap/static."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = []
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert isinstance(topic, str) and isinstance(source, str)
        assert len(topic) > 0

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_prefers_recent_arxiv_over_older_feed_topics(self, mock_load):
        """Un topic arXiv reciente (al final de la lista) se elige aunque haya
        topics phase_b_feed mas viejos delante: el fix del diagnostico de la
        agenda (limit=None + sort por created_at + filtro phase_b_feed)."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "old feed artifact", "source": "phase_b_feed", "created_at": "2026-07-15T00:00:00+00:00"},
            {"topic": "recent feed artifact", "source": "phase_b_feed", "created_at": "2026-07-20T00:00:00+00:00"},
            {
                "topic": 'production agent engineering implications of the paper "X" (arXiv:2607.99999v1) for production agent reliability',
                "source": "arxiv",
                "created_at": "2026-08-03T00:00:00+00:00",
            },
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert source == "arxiv"
        assert "arXiv:2607.99999v1" in topic

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_filters_phase_b_feed_by_default(self, mock_load):
        """Topic with source='phase_b_feed' is excluded from Phase A by default."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "feed artifact", "source": "phase_b_feed"},
        ]
        mock_load.return_value = mock_agenda
        # All topics filtered → falls through to roadmap/static fallback
        topic, source = choose_topic(mode="research")
        assert isinstance(topic, str) and isinstance(source, str)
        assert len(topic) > 0
        assert topic != "feed artifact"

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_includes_phase_b_feed_when_env_set(self, mock_load):
        """Topic with source='phase_b_feed' IS included when ALLOW_PHASE_B_FEED_TOPICS=true."""
        os.environ["ALLOW_PHASE_B_FEED_TOPICS"] = "true"
        try:
            mock_agenda = MagicMock()
            mock_agenda.get_uncovered_topics.return_value = [
                {"topic": "feed artifact", "source": "phase_b_feed"},
            ]
            mock_load.return_value = mock_agenda
            topic, source = choose_topic(mode="research")
            assert topic == "feed artifact"
            assert source == "phase_b_feed"
        finally:
            os.environ.pop("ALLOW_PHASE_B_FEED_TOPICS", None)

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_includes_human_seeded(self, mock_load):
        """Topic with source='human_seeded' is always included."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "legit topic", "source": "human_seeded"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "legit topic"
        assert source == "human_seeded"

    # ── Orden por recencia (choose_topic) ─────────────────────────

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_prioritizes_most_recent_created_at(self, mock_load):
        """choose_topic elige el topic con created_at mas reciente, no el primero de la lista."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "old topic", "source": "agenda", "created_at": "2026-07-01"},
            {"topic": "new topic", "source": "agenda", "created_at": "2026-07-20"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "new topic"
        assert source == "agenda"

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_missing_created_at_treated_as_oldest(self, mock_load):
        """Sin created_at (None/empty) el topic no debe ganarle a uno con fecha."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "no date", "source": "agenda"},
            {"topic": "has date", "source": "agenda", "created_at": "2026-07-15"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "has date"
        assert source == "agenda"

    # ── Orden por recencia (_topic_with_matrix_fallback) ──────────

    @patch("phases.phase_a_content.load_agenda")
    def test_topic_with_matrix_fallback_prioritizes_most_recent(self, mock_load):
        """_topic_with_matrix_fallback tambien ordena por created_at descendente."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "old matrix", "source": "agenda", "created_at": "2026-07-01"},
            {"topic": "new matrix", "source": "agenda", "created_at": "2026-07-20"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = _topic_with_matrix_fallback(mode="research", matrix=None)
        assert topic == "new matrix"
        assert source == "agenda"

    @patch("phases.phase_a_content.load_agenda")
    def test_topic_with_matrix_fallback_missing_created_at_oldest(self, mock_load):
        """_topic_with_matrix_fallback trata created_at ausente como el mas antiguo."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "no date matrix", "source": "agenda"},
            {"topic": "has date matrix", "source": "agenda", "created_at": "2026-07-15"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = _topic_with_matrix_fallback(mode="research", matrix=None)
        assert topic == "has date matrix"
        assert source == "agenda"

    # ── Filtro phase_b_feed con UUID (bug real en produccion) ────

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_filters_phase_b_feed_with_uuid_suffix(self, mock_load):
        """source='phase_b_feed:<uuid>' debe filtrarse igual que 'phase_b_feed' pelado."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "feed uuid", "source": "phase_b_feed:84303887-3f7c-4e51-863b-79b3344bf790",
             "created_at": "2026-07-20"},
            {"topic": "agenda topic", "source": "agenda", "created_at": "2026-07-01"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "agenda topic"
        assert source == "agenda"

    @patch("phases.phase_a_content.load_agenda")
    def test_topic_with_matrix_fallback_filters_phase_b_feed_with_uuid(self, mock_load):
        """_topic_with_matrix_fallback tambien filtra source='phase_b_feed:<uuid>'."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "feed uuid", "source": "phase_b_feed:84303887-3f7c-4e51-863b-79b3344bf790",
             "created_at": "2026-07-20"},
            {"topic": "agenda topic", "source": "agenda", "created_at": "2026-07-01"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = _topic_with_matrix_fallback(mode="research", matrix=None)
        assert topic == "agenda topic"
        assert source == "agenda"


# ── Fix 1: Pacing check antes del loop de generación ────────────

@pytest.mark.asyncio
async def test_execute_pacing_blocks_before_model_call():
    """Pacing check debe ejecutarse ANTES de llamar al modelo (no gasta LLM si no se puede publicar)."""
    from datetime import datetime, timedelta
    from phases.deps import PhaseADeps
    from phases.phase_a_content import PhaseAContentGeneration

    deps = PhaseADeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_posts_per_day": 5},
        posts_today=0,
        get_posts_today=lambda: 0,
    )

    fake_now = datetime(2026, 7, 22, 12, 0, 0)

    with (
        patch("phases.phase_a_content.datetime") as mock_dt,
        patch("phases.phase_a_content.behavior_cfg", {"max_posts_per_day": 5, "phase_a_mode": "research"}),
        patch("services.persistence.load_agent_state") as mock_state,
        patch("phases.phase_a_content.choose_topic", return_value=("test topic", "agenda")),
        patch("phases.phase_a_content._is_allowed_topic", return_value=True),
        patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
        patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
        patch("phases.phase_a_content.load_editorial_policy", return_value={}),
        patch("phases.phase_a_content.call_model") as mock_call_model,
    ):
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
        mock_state.return_value = {"last_post_timestamp": (fake_now - timedelta(minutes=3)).isoformat()}
        phase_a = PhaseAContentGeneration(deps=deps)
        result = await phase_a.execute()

        mock_call_model.assert_not_called()
        assert any(p.get("error") == "pacing_blocked" for p in result.get("posts", []))


# ── Gate de quality_filters en _looks_low_quality (menciones + min score) ──

class TestLooksLowQualityPolicyGate:
    """El parametro policy de _looks_low_quality debe aplicar quality_filters."""

    POLICY = {
        "quality_filters": {
            "reject_if_mentions_moltbook": True,
            "reject_if_mentions_llm": True,
            # off_niche tiene su propia clase de tests; aqui se aisla el
            # gate de menciones + min score.
            "reject_if_off_niche": False,
            "min_quality_score": 0.72,
        }
    }

    @staticmethod
    def _pad(text: str) -> str:
        """Rellena hasta min_length_chars sin agregar señales de scoring."""
        filler = " The team keeps refining this idea with careful attention to the craft."
        while len(text) < EDITORIAL_CONFIG["min_length_chars"]:
            text += filler
        return text

    def test_mentions_moltbook_rejected(self):
        text = self._pad(
            "Our experience posting on Moltbook shaped how we think about community norms."
        )
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason == "mentions_moltbook"

    def test_mentions_llm_rejected(self):
        text = self._pad(
            "Relying on an LLM to draft replies changes the economics of moderation work."
        )
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason == "mentions_llm"

    def test_pure_agreement_below_min_score_rejected(self):
        text = "Good point, exactly. You're right, solid engineering all around. " * 6
        assert len(text.strip()) >= EDITORIAL_CONFIG["min_length_chars"]
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason.startswith("below_min_quality_score")

    def test_empirical_text_passes_gate(self):
        text = (
            "After migrating the ingestion service, we observed a marked drop in tail "
            "spikes once the retry queue was isolated from the hot path. In production "
            "the change held up during peak traffic, and when we deployed the same "
            "isolation to the batch workers the failure cascades stopped entirely. The "
            "lesson: separating concerns at the queue boundary matters more than tuning."
        )
        assert len(text) >= EDITORIAL_CONFIG["min_length_chars"]
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is False
        assert reason == ""

    # ── Fix 6: override estructural — post largo + pregunta abierta genuina
    #    NO se rechaza aunque dual_scoring lo etiquete de bajo valor (clarification). ──

    @pytest.mark.parametrize("body", [_GOOD_SUBSTANTIVE_1, _GOOD_SUBSTANTIVE_2])
    def test_substantive_good_body_passes_override(self, body):
        # Precondicion: dual_scoring lo puntua < 0.72 (entra al bloque min_score).
        low, reason = _looks_low_quality(body, self.POLICY)
        assert low is False, f"cuerpo bueno rechazado por el gate: {reason}"
        assert reason == ""

    def test_long_generic_without_question_still_rejected(self):
        # >400 chars pero cierra con afirmacion, no pregunta -> el override NO rescata.
        text = "Good point, exactly. You're right, solid engineering all around. " * 7
        assert len(text.strip()) >= 400
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason.startswith("below_min_quality_score")


class TestIsSubstantivePost:
    """Estructura pura: post largo (>=400) que cierra con pregunta abierta de >=8
    palabras. No depende de keywords del dominio."""

    @pytest.mark.parametrize("text", [_GOOD_SUBSTANTIVE_1, _GOOD_SUBSTANTIVE_2])
    def test_substantive_true(self, text):
        assert _is_substantive_post(text) is True

    @pytest.mark.parametrize("text", [
        "Interesting take on agent loops, worth thinking about more.",  # corto
        "Good point, exactly right, solid engineering here.",           # corto + generico
        "What do you think?",                                           # pregunta pero < 400
    ])
    def test_substantive_false(self, text):
        assert _is_substantive_post(text) is False


# ── Gate off-niche en _looks_low_quality ──────────────────────────

class TestLooksLowQualityOffNiche:
    """reject_if_off_niche exige que el texto mencione el nicho (agentes) o
    alguna palabra de topic_weights."""

    POLICY = {
        "quality_filters": {"reject_if_off_niche": True},
        "topic_weights": {"observability for multi-step workflows": 1.0},
    }

    RECIPE = (
        "Start by simmering the tomatoes over low heat until they break down "
        "into a rich sauce, then fold in the fresh basil and a generous pour "
        "of olive oil. Season the dish and let the flavors meld overnight "
        "before serving it alongside crusty bread and a bright salad."
    )

    @staticmethod
    def _pad(text: str) -> str:
        filler = " The team keeps refining the recipe over many quiet evenings at home."
        while len(text) < EDITORIAL_CONFIG["min_length_chars"]:
            text += filler
        return text

    def test_niche_mention_not_rejected(self):
        text = self._pad(
            "Running an autonomous agent in production surfaces failure modes "
            "that never appear in local runs, especially around retries."
        )
        low, reason = _looks_low_quality(text, self.POLICY)
        assert reason != "off_niche"
        assert low is False

    def test_topic_weights_word_not_rejected(self):
        text = self._pad(
            "Good observability changes which incidents you even notice, and "
            "which quiet regressions slip past every reviewer unnoticed."
        )
        low, reason = _looks_low_quality(text, self.POLICY)
        assert reason != "off_niche"
        assert low is False

    def test_off_niche_text_rejected(self):
        low, reason = _looks_low_quality(self._pad(self.RECIPE), self.POLICY)
        assert low is True
        assert reason == "off_niche"

    def test_off_niche_disabled_not_rejected(self):
        policy = {"quality_filters": {"reject_if_off_niche": False}}
        low, reason = _looks_low_quality(self._pad(self.RECIPE), policy)
        assert low is False
        assert reason == ""


# ── Retry inteligente: _build_retry_correction + registro de intentos ──

class TestBuildRetryCorrection:
    """Cada motivo de rechazo se traduce en una correccion no vacia y coherente."""

    def test_below_min_quality_score_names_content_type(self):
        correction = _build_retry_correction("below_min_quality_score:0.3:clarification")
        assert correction.startswith("\n\nCORRECCION DEL INTENTO ANTERIOR:")
        assert "'clarification'" in correction
        assert "peso tecnico" in correction

    def test_validation_failed_maps_sub_reason(self):
        correction = _build_retry_correction("validation_failed:contains_error_log")
        assert correction.startswith("\n\nCORRECCION DEL INTENTO ANTERIOR:")
        assert "log de error" in correction

    def test_similar_recent_asks_for_new_angle(self):
        correction = _build_retry_correction("similar_recent")
        assert correction.startswith("\n\nCORRECCION DEL INTENTO ANTERIOR:")
        assert "angulo distinto" in correction

    def test_unknown_reason_gets_generic_hint(self):
        correction = _build_retry_correction("razon_inexistente_xyz")
        assert correction.startswith("\n\nCORRECCION DEL INTENTO ANTERIOR:")
        assert "razon_inexistente_xyz" in correction

    def test_empty_reason_returns_empty(self):
        assert _build_retry_correction("") == ""


class TestLogGenerationAttempt:
    def test_writes_valid_jsonl_record(self, monkeypatch, tmp_path):
        import json
        log_path = tmp_path / "generation_attempts.jsonl"
        monkeypatch.setattr("phases.phase_a_content._GENERATION_ATTEMPTS_LOG", log_path)

        _log_generation_attempt("un tema", "arxiv", 2, 3, "validation_failed:too_short")

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["topic"] == "un tema"
        assert record["topic_source"] == "arxiv"
        assert record["attempt"] == 2
        assert record["max_attempts"] == 3
        assert record["outcome"] == "validation_failed:too_short"
        assert record["timestamp"]  # ISO no vacio


@pytest.mark.asyncio
async def test_retry_sends_correction_in_second_attempt(monkeypatch, tmp_path):
    """Intento 1 rechazado (empty_output) → el user_prompt del intento 2 lleva la correccion."""
    from datetime import datetime
    from phases.deps import PhaseADeps
    from phases.phase_a_content import PhaseAContentGeneration

    monkeypatch.setattr(
        "phases.phase_a_content._GENERATION_ATTEMPTS_LOG",
        tmp_path / "generation_attempts.jsonl",
    )

    valid_text = (
        "Retry loop integration check\n\n"
        "We spent three weeks tracing why our retry queue kept starving the primary "
        "workers during peak load in production, and the answer turned out to be a "
        "lock held far longer than anyone assumed.\n\n"
        "Once we moved the bookkeeping out of the critical section, the starvation "
        "disappeared and throughput recovered. The lesson we keep relearning: measure "
        "the hot path before blaming the scheduler, because intuition about contention "
        "is usually wrong."
    )

    deps = PhaseADeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_posts_per_day": 5},
        posts_today=0,
        get_posts_today=lambda: 0,
    )

    fake_now = datetime(2026, 7, 22, 12, 0, 0)
    mock_call_model = AsyncMock(side_effect=["", valid_text])

    with (
        patch("phases.phase_a_content.datetime") as mock_dt,
        patch("phases.phase_a_content.behavior_cfg",
              {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
        patch("services.persistence.load_agent_state", return_value={}),
        patch("services.own_post_store.count_posts_since", return_value=0),
        patch("phases.phase_a_content.choose_topic", return_value=("test topic", "agenda")),
        patch("phases.phase_a_content.load_topic_matrix", return_value=None),
        patch("phases.phase_a_content._is_allowed_topic", return_value=True),
        patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
        patch("phases.phase_a_content.build_prompts", return_value=("sys", "user prompt base")),
        patch("phases.phase_a_content.load_editorial_policy", return_value={}),
        patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
        patch("phases.phase_a_content.call_model", new=mock_call_model),
    ):
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
        phase_a = PhaseAContentGeneration(deps=deps)
        result = await phase_a.execute()

    assert mock_call_model.call_count == 2, f"esperaba 2 intentos, hubo {mock_call_model.call_count}"
    first_prompt = mock_call_model.call_args_list[0].args[2]
    second_prompt = mock_call_model.call_args_list[1].args[2]
    assert first_prompt == "user prompt base"
    assert "CORRECCION DEL INTENTO ANTERIOR" in second_prompt
    assert second_prompt.startswith("user prompt base")
    # y el intento 2 termino en post generado (whisper: no se publica)
    assert result["drafts_generated"] == 1


# ── Cita verificable arXiv en el body (brecha de especificidad) ─────────────
_ARXIV_TOPIC = (
    'production agent engineering implications of the paper "The Shared Discovery '
    'Paradox" (arXiv:2607.18045v1) for production agent reliability and orchestration'
)
_ARXIV_BODY = (
    "The fix is a rolling re-injection trigger that tracks distance in tokens since "
    "the last critical directive and re-inserts a compressed core-constraints preamble "
    "past sixty percent of the effective recall horizon. This resets the attention "
    "baseline without duplicating full history, and catches the identity drift that "
    "precedes every silent failure.\n\n"
    "Where do you place the re-injected directive when the tool output stream is "
    "already dense, and how do you measure the tradeoff between preamble cost and "
    "drift prevention."
)


class TestArxivCitation:
    def test_extract_arxiv_id_from_anchored_topic(self):
        assert _extract_arxiv_id(_ARXIV_TOPIC) == "2607.18045v1"

    def test_extract_arxiv_id_plain_topic_returns_none(self):
        assert _extract_arxiv_id("agent tool safety") is None
        assert _extract_arxiv_id("") is None

    def test_build_prompts_arxiv_topic_adds_citation_instruction(self):
        for mode in ("research", "expository"):
            sys_prompt, user_prompt = build_prompts(_ARXIV_TOPIC, mode=mode)
            assert "HARD REQUIREMENT" in user_prompt
            assert "(arXiv:2607.18045v1)" in user_prompt
            assert "TITLE must NOT contain the arXiv identifier" in user_prompt
            assert "FIRST paragraph" in user_prompt
            assert "SOURCE ANCHOR" in sys_prompt
            assert "arXiv:2607.18045v1" in sys_prompt

    def test_build_prompts_plain_topic_has_no_citation_instruction(self):
        sys_prompt, user_prompt = build_prompts("agent tool safety", mode="research")
        assert "HARD REQUIREMENT" not in user_prompt
        assert "SOURCE ANCHOR" not in sys_prompt

    def test_validate_rejects_body_without_citation(self):
        valid, reason = validate_post_text(_ARXIV_BODY, required_citation="2607.18045v1")
        assert valid is False
        assert reason == "missing_arxiv_citation"

    def test_validate_accepts_body_with_citation(self):
        body = "The paper (arXiv:2607.18045v1) shows a parallel result. " + _ARXIV_BODY
        valid, reason = validate_post_text(body, required_citation="2607.18045v1")
        assert valid is True
        assert reason == "ok"

    def test_validate_tolerates_missing_version_suffix(self):
        body = "The paper (arXiv:2607.18045) shows a parallel result. " + _ARXIV_BODY
        valid, reason = validate_post_text(body, required_citation="2607.18045v1")
        assert valid is True
        assert reason == "ok"

    def test_validate_without_required_citation_keeps_old_behavior(self):
        valid, reason = validate_post_text(_ARXIV_BODY)
        assert valid is True
        assert reason == "ok"

    def test_paper_title_and_arxiv_id_extraction(self):
        title, arxiv_id = _paper_title_and_arxiv_id(_ARXIV_TOPIC)
        assert title == "The Shared Discovery Paradox"
        assert arxiv_id == "2607.18045v1"

    def test_paper_title_and_arxiv_id_plain_topic(self):
        title, arxiv_id = _paper_title_and_arxiv_id("agent tool safety")
        assert title is None
        assert arxiv_id is None

    @pytest.mark.asyncio
    async def test_arxiv_citation_injected_when_model_wont_cite(self):
        """Si el modelo no cita el arXiv ID en N intentos, el pipeline inyecta
        'Source: <titulo> (arXiv:ID)' al final del body en vez de descartar el post."""
        from phases.phase_a_content import PhaseAContentGeneration
        from phases.deps import PhaseADeps
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import datetime

        deps = PhaseADeps(
            model_cascade=AsyncMock(),
            moltbook_client=MagicMock(),
            behavior_cfg={"max_posts_per_day": 5},
            posts_today=0,
            get_posts_today=lambda: 0,
        )
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        model_body = (
            "Retry loop integration check\n\n"
            "We spent three weeks tracing why our retry queue kept starving the primary "
            "workers during peak load in production, and the answer turned out to be a "
            "lock held far longer than anyone assumed.\n\n"
            "Once we moved the bookkeeping out of the critical section, the starvation "
            "disappeared and throughput recovered. The lesson we keep relearning: measure "
            "the hot path before blaming the scheduler, because intuition about contention "
            "is usually wrong."
        )
        mock_call_model = AsyncMock(return_value=model_body)

        with (
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 1}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic", return_value=(_ARXIV_TOPIC, "arxiv")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch("phases.phase_a_content._is_allowed_topic", return_value=True),
            patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            phase_a = PhaseAContentGeneration(deps=deps)
            result = await phase_a.execute()

        assert result["drafts_generated"] == 1
        assert mock_call_model.call_count == 1
        draft = result["posts"][0]
        assert draft.get("error") is None
        assert "Source: The Shared Discovery Paradox (arXiv:2607.18045v1)" in draft["body"]
        assert "missing_arxiv_citation" not in str(draft.get("metadata", {}))

    @pytest.mark.asyncio
    async def test_arxiv_citation_injected_on_first_attempt_no_rejection(self, monkeypatch, tmp_path):
        """Candidato valido sin cita + tema con arXiv id → se ACEPTA con la cita
        inyectada en el PRIMER intento: una sola llamada al modelo (no reintenta),
        no se registra rechazo (ni validation_failed ni rejected_posts)."""
        from phases.phase_a_content import PhaseAContentGeneration
        from phases.deps import PhaseADeps
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import datetime

        attempts_log = tmp_path / "generation_attempts.jsonl"
        monkeypatch.setattr("phases.phase_a_content._GENERATION_ATTEMPTS_LOG", attempts_log)
        rejected_log = tmp_path / "rejected_posts.jsonl"
        monkeypatch.setattr("phases.phase_a_content._REJECTED_POSTS_LOG", rejected_log)

        deps = PhaseADeps(
            model_cascade=AsyncMock(),
            moltbook_client=MagicMock(),
            behavior_cfg={"max_posts_per_day": 5},
            posts_today=0,
            get_posts_today=lambda: 0,
        )
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        model_body = (
            "The retrieval guardrail that actually holds\n\n"
            "We spent three weeks tracing why our retry queue kept starving the "
            "primary workers during peak load in production, and the answer turned "
            "out to be a lock held far longer than anyone assumed. Once we moved "
            "the bookkeeping out of the critical section, the starvation "
            "disappeared and throughput recovered.\n\n"
            "The lesson we keep relearning: measure the hot path before blaming "
            "the scheduler, because intuition about contention is usually wrong. "
            "A rolling divergence gate on the value head catches drift before "
            "task success metrics crater, and it reuses telemetry you already "
            "have on hand."
        )
        mock_call_model = AsyncMock(return_value=model_body)

        with (
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic", return_value=(_ARXIV_TOPIC, "arxiv")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch("phases.phase_a_content._is_allowed_topic", return_value=True),
            patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            phase_a = PhaseAContentGeneration(deps=deps)
            result = await phase_a.execute()

        assert mock_call_model.call_count == 1, f"no reintenta: 1 llamada, hubo {mock_call_model.call_count}"
        assert result["drafts_generated"] == 1
        draft = result["posts"][0]
        assert draft.get("error") is None
        assert draft["metadata"]["attempts"] == 1
        assert "Source: The Shared Discovery Paradox (arXiv:2607.18045v1)" in draft["body"]
        assert "missing_arxiv_citation" not in str(draft.get("metadata", {}))
        # no cuenta como rechazo: sin validation_failed y sin rejected_posts
        log_text = attempts_log.read_text(encoding="utf-8") if attempts_log.exists() else ""
        assert "validation_failed" not in log_text
        assert "success_arxiv_injected" in log_text
        assert not rejected_log.exists(), "no se registra rechazo para cita faltante en topic arXiv"
