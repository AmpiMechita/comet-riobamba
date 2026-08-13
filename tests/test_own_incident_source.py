# -*- coding: utf-8 -*-
"""Tests del store de incidentes reales y la fuente own_incident de Phase A.

Cubre el contrato de la feature:
- own_incident se selecciona con prioridad alta y pasa el filtro editorial
- un incidente usado no se repite (used=True)
- el prompt incluye los numeros reales del incidente
- un post generado desde own_incident NO dispara fabricated_measurement
- BLOCKED sigue bloqueando aunque venga de own_incident
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = ("pytest_asyncio",)

import services.incident_store as incident_store
from phases.phase_a_content import (
    build_prompts, choose_topic, _apply_editorial_filter, validate_post_text,
    EDITORIAL_CONFIG, _count_incident_figures, INCIDENT_MIN_FIGURES,
    _build_retry_correction,
)
from services.incident_store import extract_incident_figures


def _incident(inc_id="inc-test-1", used=False):
    return {
        "id": inc_id,
        "date": "2026-08-12",
        "title": f"The inbound metric that read zero for three days: a field-name mismatch ({inc_id})",
        "symptom": "A production agent ran for days on an inbound metric that read zero. 410 of 410 log lines attributed the commenter to 'unknown'.",
        "root_cause": "One component normalized the commenter field under a different key than the one the consumer read, so every lookup silently missed.",
        "fix": "Align the read path with the canonical field name.",
        "real_numbers": "410/410 log lines said 'unknown'; the metric read 0.",
        "used": used,
    }


def _seed(records):
    path = incident_store.INCIDENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


class FakeAgenda:
    def __init__(self):
        self.pending_topics = []

    def add_topic(self, topic, source="", tags=None):
        existing = {t["topic"] for t in self.pending_topics}
        if topic not in existing:
            self.pending_topics.append({
                "topic": topic, "source": source, "tags": tags or [],
                "covered": False, "created_at": "2026-08-12T00:00:00+00:00",
            })


# ── Store: used / no-repetition ──────────────────────────────────

class TestIncidentStore:
    def test_get_unused_skips_used(self):
        _seed([_incident("inc-used", used=True), _incident("inc-fresh", used=False)])
        inc = incident_store.get_unused_incident()
        assert inc is not None
        assert inc["id"] == "inc-fresh"

    def test_all_used_returns_none(self):
        _seed([_incident("inc-a", used=True), _incident("inc-b", used=True)])
        assert incident_store.get_unused_incident() is None

    def test_mark_used_persists_and_is_idempotent(self):
        _seed([_incident("inc-x", used=False)])
        assert incident_store.mark_incident_used("inc-x") is True
        records = incident_store.load_incidents()
        assert records[0]["used"] is True
        assert incident_store.mark_incident_used("inc-x") is False

    def test_get_by_id(self):
        _seed([_incident("inc-x", used=False)])
        assert incident_store.get_incident_by_id("inc-x")["id"] == "inc-x"
        assert incident_store.get_incident_by_id("inc-nope") is None

    def test_marked_used_not_re_registered(self):
        _seed([_incident("inc-x", used=False)])
        agenda = FakeAgenda()
        incident_store.register_incidents(agenda)
        assert incident_store.mark_incident_used("inc-x") is True
        agenda2 = FakeAgenda()
        added = incident_store.register_incidents(agenda2)
        assert added == 0
        assert len(agenda2.pending_topics) == 0


class TestRegisterIncidents:
    def test_registers_unused_with_own_incident_source(self):
        _seed([_incident("inc-a", used=False), _incident("inc-b", used=False), _incident("inc-used", used=True)])
        agenda = FakeAgenda()
        added = incident_store.register_incidents(agenda)
        assert added == 2
        assert len(agenda.pending_topics) == 2
        for t in agenda.pending_topics:
            assert t["source"].startswith("own_incident:")
            assert "own_incident" in t["tags"]
            assert "verifiable" in t["tags"]

    def test_idempotent_and_completes_queue(self):
        _seed([_incident("inc-a", used=False), _incident("inc-b", used=False)])
        agenda = FakeAgenda()
        incident_store.register_incidents(agenda, max_topics=1)
        assert len(agenda.pending_topics) == 1
        added_second = incident_store.register_incidents(agenda, max_topics=1)
        assert added_second == 1
        assert len(agenda.pending_topics) == 2
        assert incident_store.register_incidents(agenda, max_topics=1) == 0


# ── Filtro editorial: exencion de own_incident ───────────────────

class TestEditorialFilterOwnIncident:
    def test_own_incident_off_niche_passes(self):
        topic = "The configured value that silently became the default"
        assert not _is_allowed_topic_for(topic)
        result_topic, result_source = _apply_editorial_filter(topic, "own_incident:inc-x")
        assert result_topic == topic
        assert result_source == "own_incident:inc-x"

    def test_blocked_signal_still_blocked_even_own_incident(self):
        topic = "blockchain consensus for agents"
        result_topic, result_source = _apply_editorial_filter(topic, "own_incident:inc-x")
        assert result_topic == "context window exhaustion in long-running agents"
        assert result_source == "fallback_filter"


def _is_allowed_topic_for(topic: str) -> bool:
    from phases.phase_a_content import _is_allowed_topic
    return _is_allowed_topic(topic)


# ── Gate de cifras verificadas (patron arXiv: la instruccion no alcanza) ──

_NESTED_INCIDENT = {
    "id": "inc-20260812-nested-replies",
    "date": "2026-08-12",
    "title": "The agent that was blind to nested replies",
    "symptom": "Reply matching produced 0 matches over 1,035 inspected comments: every threaded response was invisible.",
    "root_cause": "The fetch returned only top-level comments while the API nests replies inside their parent, so the matcher never saw them.",
    "fix": "Flatten nested replies recursively preserving parent ids, and apply the same parent extraction to follow-up matching, depth guards and thread depth computation.",
    "real_numbers": "1,035 comments inspected; 0 replies matched before the fix.",
    "used": False,
}

_NO_FIGURES_BODY = (
    "Nested replies the matcher never saw\n\n"
    "An agent's reply matcher that relies on a flat list of top-level comments "
    "keeps scoring the same invisible threads every cycle, no matter how "
    "carefully the drafts are written.\n\n"
    "The fix is a recursive flattening pass that preserves parent ids and feeds "
    "the same extraction into follow-up matching and depth guards. A production "
    "agent that only reads top-level comments is not having a conversation; it "
    "is reading one side of the mail.\n\n"
    "What does your comment fetch return today that the platform nests one "
    "level deeper than you assumed?"
)

_WITH_FIGURES_BODY = (
    "The agent that scored a thousand comments and matched none\n\n"
    "An agent's reply matching produced 0 matches over 1,035 inspected "
    "comments: every threaded response was invisible because the fetch "
    "returned only top-level comments while the API nests replies inside "
    "their parent.\n\n"
    "The fix is a recursive flattening pass that preserves parent ids and "
    "feeds the same extraction into follow-up matching, depth guards and "
    "thread depth computation. 0 matches on 1,035 comments is not a lack of "
    "interest in the conversation; it is a parsing bug wearing the costume "
    "of silence.\n\n"
    "Does your comment fetch read the nested field, or only the list you "
    "asked for?"
)


class TestIncidentFigures:
    def test_extract_figures_from_real_numbers(self):
        figures = extract_incident_figures(_NESTED_INCIDENT)
        assert "1,035" in figures
        assert "0" in figures

    def test_extract_figures_richer_and_plain_tokens_coexist(self):
        inc = {
            "id": "i1", "title": "t",
            "symptom": "",
            "root_cause": "",
            "fix": "",
            "real_numbers": "Daily budget cut 80->30 comments/day; 4 rejections; 9/50 -> 18/50 -> 27/50 -> 24/50 low-value.",
            "used": False,
        }
        figures = extract_incident_figures(inc)
        assert "80->30" in figures
        assert "9/50" in figures
        assert "24/50" in figures
        assert "0" in extract_incident_figures(_NESTED_INCIDENT), "0 matches es cifra clave aunque '0' viva dentro de '1,035'"

    def test_empty_incident_returns_empty(self):
        assert extract_incident_figures(None) == []
        assert extract_incident_figures({}) == []

    def test_count_two_figures_present(self):
        present, missing = _count_incident_figures(_WITH_FIGURES_BODY, ["1,035", "0"])
        assert present == 2
        assert missing == []

    def test_count_one_figure_present(self):
        present, missing = _count_incident_figures(_NO_FIGURES_BODY, ["1,035", "0"])
        assert present == 0
        assert set(missing) == {"1,035", "0"}

    def test_count_no_substring_false_positives(self):
        present, _ = _count_incident_figures("the number 1050 appears here", ["50", "12"])
        assert present == 0

    def test_count_tolerates_missing_thousands_separator(self):
        present, missing = _count_incident_figures("over 1035 comments inspected", ["1,035", "0"])
        assert present == 1
        assert missing == ["0"]

    def test_min_figures_constant_is_two(self):
        assert INCIDENT_MIN_FIGURES == 2


class TestBuildPromptsIncidentFigures:
    def test_prompt_hard_requirement_lists_figures(self):
        _, user_prompt = build_prompts(
            _NESTED_INCIDENT["title"],
            incident=_NESTED_INCIDENT,
            incident_figures=["1,035", "0"],
        )
        assert "HARD REQUIREMENT (non-negotiable)" in user_prompt
        assert "at least TWO of these verified figures" in user_prompt
        assert "'1,035'" in user_prompt
        assert "'0'" in user_prompt
        assert "Do NOT invent any additional number" in user_prompt

    def test_plain_topic_has_no_hard_requirement(self):
        _, user_prompt = build_prompts("agent tool safety")
        assert "HARD REQUIREMENT (non-negotiable)" not in user_prompt


class TestIncidentFiguresGate:
    """El gate rechaza sin cifras (y NO quema el incidente) y acepta con 2+."""

    def _deps(self):
        from phases.deps import PhaseADeps
        return PhaseADeps(
            model_cascade=AsyncMock(),
            moltbook_client=MagicMock(),
            behavior_cfg={"max_posts_per_day": 5},
            posts_today=0,
            get_posts_today=lambda: 0,
        )

    @pytest.mark.asyncio
    async def test_body_without_figures_rejected_and_incident_stays_unused(self, tmp_path):
        from phases.phase_a_content import PhaseAContentGeneration
        from phases.deps import PhaseADeps

        _seed([dict(_NESTED_INCIDENT)])
        deps = self._deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(return_value=_NO_FIGURES_BODY)

        with (
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 1}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=(_NESTED_INCIDENT["title"], "own_incident:inc-20260812-nested-replies")),
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
        assert result["posts"][0].get("error") == "validation_failed:missing_incident_figures"
        records = incident_store.load_incidents()
        assert records[0]["used"] is False, "el incidente NO debe quemarse si el post no pasa el gate"

    @pytest.mark.asyncio
    async def test_body_with_two_figures_published_and_marked_used(self, tmp_path):
        from phases.phase_a_content import PhaseAContentGeneration

        _seed([dict(_NESTED_INCIDENT)])
        deps = self._deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(return_value=_WITH_FIGURES_BODY)
        deps.moltbook_client.create_post = MagicMock(
            return_value={"success": True, "status": 201, "id": "post-incident-2", "raw": {}}
        )

        with (
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research"}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=(_NESTED_INCIDENT["title"], "own_incident:inc-20260812-nested-replies")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch.multiple("phases.phase_a_content",
                           _is_allowed_topic=MagicMock(return_value=True),
                           _is_topic_recently_used=MagicMock(return_value=False),
                           is_similar_to_recent=MagicMock(return_value=False)),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
            patch.multiple("phases.phase_a_content",
                           store_post_hash=MagicMock(),
                           _save_published_post=MagicMock(),
                           _track_topic_performance=MagicMock(),
                           _record_topic_used=MagicMock(),
                           mark_examples_used=MagicMock(),
                           log_dual_score=MagicMock()),
            patch("phases.phase_a_content.load_agenda") as mock_agenda,
            patch("phases.phase_a_content.asyncio.sleep", new=AsyncMock()),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            mock_agenda.return_value = MagicMock()
            phase_a = PhaseAContentGeneration(deps=deps)
            phase_a._dry_run_flag_phase_a = Path("data/phase_a_dry_run.flag.does-not-exist-for-tests")
            result = await phase_a.execute()

        assert result["posts_published"] == 1
        assert result["posts"][0]["published"] is True
        records = incident_store.load_incidents()
        assert records[0]["used"] is True, "el incidente se marca usado al publicar con cifras"

    @pytest.mark.asyncio
    async def test_retry_correction_names_missing_figures(self, tmp_path):
        from phases.phase_a_content import PhaseAContentGeneration

        _seed([dict(_NESTED_INCIDENT)])
        deps = self._deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(side_effect=[_NO_FIGURES_BODY, _WITH_FIGURES_BODY])
        deps.moltbook_client.create_post = MagicMock(
            return_value={"success": True, "status": 201, "id": "post-incident-3", "raw": {}}
        )

        with (
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research"}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 2}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=(_NESTED_INCIDENT["title"], "own_incident:inc-20260812-nested-replies")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch.multiple("phases.phase_a_content",
                           _is_allowed_topic=MagicMock(return_value=True),
                           _is_topic_recently_used=MagicMock(return_value=False),
                           is_similar_to_recent=MagicMock(return_value=False)),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user prompt base")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
            patch.multiple("phases.phase_a_content",
                           store_post_hash=MagicMock(),
                           _save_published_post=MagicMock(),
                           _track_topic_performance=MagicMock(),
                           _record_topic_used=MagicMock(),
                           mark_examples_used=MagicMock(),
                           log_dual_score=MagicMock()),
            patch("phases.phase_a_content.load_agenda") as mock_agenda,
            patch("phases.phase_a_content.asyncio.sleep", new=AsyncMock()),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            mock_agenda.return_value = MagicMock()
            phase_a = PhaseAContentGeneration(deps=deps)
            phase_a._dry_run_flag_phase_a = Path("data/phase_a_dry_run.flag.does-not-exist-for-tests")
            result = await phase_a.execute()

        assert mock_call_model.call_count == 2, "el intento 1 se rechaza por cifras, el 2 corrige"
        second_prompt = mock_call_model.call_args_list[1].args[2]
        assert "CORRECCION DEL INTENTO ANTERIOR" in second_prompt
        assert "1,035" in second_prompt, "la correccion debe nombrar las cifras faltantes"
        assert result["posts_published"] == 1
        records = incident_store.load_incidents()
        assert records[0]["used"] is True


# ── Prioridad alta en choose_topic (al nivel de watchlist_pairing) ──

class TestChooseTopicOwnIncidentPriority:
    @patch("phases.phase_a_content.load_agenda")
    def test_own_incident_chosen_over_plain_agenda(self, mock_load):
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "plain agenda topic", "source": "agenda", "created_at": "2026-08-12T01:00:00+00:00"},
            {"topic": "The inbound metric that read zero for three days: a field-name mismatch",
             "source": "own_incident:inc-x", "created_at": "2026-08-12T02:00:00+00:00"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert source.startswith("own_incident:")

    @patch("phases.phase_a_content.load_agenda")
    def test_same_priority_class_as_watchlist(self, mock_load):
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "Counter-claim to the position by watchlist author",
             "source": "watchlist_pairing:abc", "created_at": "2026-08-12T03:00:00+00:00"},
            {"topic": "The inbound metric that read zero for three days: a field-name mismatch",
             "source": "own_incident:inc-x", "created_at": "2026-08-12T02:00:00+00:00"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert source == "watchlist_pairing:abc"  # mismo nivel: gana el mas reciente

    @patch("phases.phase_a_content.load_agenda")
    def test_own_incident_wins_when_newer_than_watchlist(self, mock_load):
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "Counter-claim to the position by watchlist author",
             "source": "watchlist_pairing:abc", "created_at": "2026-08-12T01:00:00+00:00"},
            {"topic": "The inbound metric that read zero for three days: a field-name mismatch",
             "source": "own_incident:inc-x", "created_at": "2026-08-12T04:00:00+00:00"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert source.startswith("own_incident:")


# ── Prompt: contexto factual con los numeros reales ─────────────

class TestBuildPromptsIncident:
    def test_prompt_includes_verified_numbers_and_instruction(self):
        _, user_prompt = build_prompts(
            _incident()["title"], incident=_incident(),
        )
        assert "FACTUAL CONTEXT" in user_prompt
        assert "410/410" in user_prompt
        assert "Symptom:" in user_prompt
        assert "Root cause:" in user_prompt
        assert "Fix:" in user_prompt
        assert "These are real, verified specifics. Use them exactly. Do NOT " \
               "invent any additional number, date, or outcome beyond what is provided." in user_prompt

    def test_plain_topic_has_no_factual_context(self):
        _, user_prompt = build_prompts("agent tool safety")
        assert "FACTUAL CONTEXT" not in user_prompt
        assert "410/410" not in user_prompt

    def test_incident_without_required_fields_does_not_crash(self):
        _, user_prompt = build_prompts("some topic", incident={"id": "inc-y"})
        assert "INSTRUCTION" in user_prompt


# ── Guard anti-fabricacion intacto ───────────────────────────────

_INCIDENT_BODY = (
    "The metric that read zero for three days\n\n"
    "A production agent ran three days on a metric that read 0. The field "
    "existed; the key did not match. 410/410 log lines said 'unknown', so "
    "the inbound signal never moved.\n\n"
    "The fix is a canonical key contract: the consumer reads the same field the "
    "client normalizes, and a contract test asserts the pair stays aligned. "
    "An agent that reads a derived field by a guessed name is not observing "
    "its system; it is rehearsing blindness.\n\n"
    "What field does your telemetry read today that the writer renamed quietly "
    "last month?"
)

_FABRICATED_BODY = (
    "We measured 410 of 410 log lines that said 'unknown' while the metric read "
    "zero for three days in a row, and we tracked every single one of them by "
    "hand in production, which took us the better part of a week.\n\n"
    "Once we aligned the field names the inbound signal recovered and the "
    "dashboard finally moved, proving that the mismatch was the whole story "
    "and the fix was exactly what we deployed."
)


class TestFabricationGuardOnIncidentPosts:
    def test_own_incident_body_does_not_trigger_guard(self):
        assert len(_INCIDENT_BODY) >= EDITORIAL_CONFIG["min_length_chars"]
        valid, reason = validate_post_text(_INCIDENT_BODY)
        assert reason != "fabricated_measurement"
        assert valid is True

    def test_first_person_version_still_rejected(self):
        assert len(_FABRICATED_BODY) >= EDITORIAL_CONFIG["min_length_chars"]
        valid, reason = validate_post_text(_FABRICATED_BODY)
        assert valid is False
        assert reason == "fabricated_measurement"


# ── Guard ampliado (v5.4) + exencion own_incident ───────────────

_PULLED_BODY = (
    "We pulled 5,000 rows from the production queue over a full week and the "
    "result was unambiguous: the retry path never fired once for the failure "
    "class that mattered most, which cost us a whole deployment cycle.\n\n"
    "The fix is a circuit that treats the retry budget as a first-class state "
    "machine, and the numbers we collected made the boundary condition obvious "
    "to every engineer on call."
)


class TestFabricationGuardExpansion:
    def test_we_pulled_rejected_in_normal_mode(self):
        """'We pulled 5,000 rows' (verbo coloquial) ahora dispara el guard."""
        assert len(_PULLED_BODY) >= EDITORIAL_CONFIG["min_length_chars"]
        valid, reason = validate_post_text(_PULLED_BODY)
        assert valid is False
        assert reason == "fabricated_measurement"

    def test_we_pulled_accepted_in_own_incident_mode(self):
        """El mismo texto en modo own_incident queda EXENTO (numeros del store)."""
        valid, reason = validate_post_text(_PULLED_BODY, is_own_incident=True)
        assert valid is True
        assert reason == "ok"

    @pytest.mark.parametrize("verb", ["saw", "found", "hit", "logged", "counted", "watched", "caught", "shipped", "pulled"])
    def test_new_verbs_all_trip_the_guard(self, verb):
        text = (
            f"After the migration we {verb} 1,200 errors in the first hour of "
            "production traffic and traced each one to the same queue.\n\n"
            "The fix is a check that treats the queue as a state machine and "
            "fails loudly the moment the count diverges from the expected "
            "distribution, which is what every operator should demand."
        )
        assert len(text) >= EDITORIAL_CONFIG["min_length_chars"]
        valid, reason = validate_post_text(text)
        assert valid is False
        assert reason == "fabricated_measurement", f"verbo '{verb}' debe disparar el guard"


# ── Vertical 3: interseccion fisica/economica con IA ─────────────

class TestAllowedTopicIntersection:
    def test_intersection_topic_passes_gate(self):
        for topic in (
            "inference cost and datacenter power limits for agent pipelines",
            "the power envelope of large model serving clusters",
            "thermal constraints forcing compute budget trade-offs in agents",
            "grid capacity and energy per token for autonomous systems",
        ):
            assert _is_allowed_topic_for(topic), f"debe pasar el gate: {topic}"

    def test_generic_energy_without_ai_link_still_blocked(self):
        for topic in (
            "solar energy market trends",
            "wind turbine output forecasts",
            "hydrogen fuel economics",
        ):
            assert not _is_allowed_topic_for(topic), f"energia generica debe seguir bloqueada: {topic}"
            result_topic, _ = _apply_editorial_filter(topic, "agenda")
            assert result_topic == "context window exhaustion in long-running agents"


# ── Execute: marca used=True al publicar ─────────────────────────

@pytest.mark.asyncio
async def test_execute_marks_incident_used_on_publish():
    from phases.deps import PhaseADeps
    from phases.phase_a_content import PhaseAContentGeneration

    _seed([_incident("inc-pub", used=False)])

    deps = PhaseADeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_posts_per_day": 5},
        posts_today=0,
        get_posts_today=lambda: 0,
    )
    fake_now = datetime(2026, 7, 22, 12, 0, 0)
    mock_call_model = AsyncMock(return_value=_INCIDENT_BODY)
    mock_create_post = MagicMock(
        return_value={"success": True, "status": 201, "id": "post-incident-1", "raw": {}}
    )
    deps.moltbook_client.create_post = mock_create_post

    with (
        patch("phases.phase_a_content.datetime") as mock_dt,
        patch("phases.phase_a_content.behavior_cfg",
              {"max_posts_per_day": 5, "phase_a_mode": "research"}),
        patch("services.persistence.load_agent_state", return_value={}),
        patch("services.own_post_store.count_posts_since", return_value=0),
        patch("phases.phase_a_content.choose_topic",
              return_value=(_incident("inc-pub")["title"], "own_incident:inc-pub")),
        patch("phases.phase_a_content.load_topic_matrix", return_value=None),
        patch("phases.phase_a_content._is_allowed_topic", return_value=True),
        patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
        patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
        patch("phases.phase_a_content.load_editorial_policy", return_value={}),
        patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
        patch("phases.phase_a_content.call_model", new=mock_call_model),
        patch("phases.phase_a_content.store_post_hash"),
        patch("phases.phase_a_content._save_published_post"),
        patch("phases.phase_a_content._track_topic_performance"),
        patch("phases.phase_a_content._record_topic_used"),
        patch("phases.phase_a_content.mark_examples_used"),
        patch("phases.phase_a_content.log_dual_score"),
        patch("phases.phase_a_content.load_agenda") as mock_agenda,
        patch("phases.phase_a_content.asyncio.sleep", new=AsyncMock()),
    ):
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
        mock_agenda.return_value = MagicMock()
        phase_a = PhaseAContentGeneration(deps=deps)
        phase_a._dry_run_flag_phase_a = Path("data/phase_a_dry_run.flag.does-not-exist-for-tests")
        result = await phase_a.execute()

    assert result["posts_published"] == 1
    assert result["posts"][0]["published"] is True
    records = incident_store.load_incidents()
    assert records[0]["id"] == "inc-pub"
    assert records[0]["used"] is True, "el incidente debe marcarse usado al publicar"
