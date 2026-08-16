"""Tests — guard de repeticion por post (parafrasis del mismo argumento en
un mismo thread).

Historia: nacieron RED (16/8/2026) reproduciendo el hilo de bytes: el agente
publicaba decenas de variaciones del MISMO argumento con vocabulario distinto.
El fix de Fase 1 cerró tres huecos que estos tests fijan como contrato:

  T1) _check_and_prevent_duplicate ahora usa señal combinada scoped al mismo
      post (is_same_thread_duplicate_reply: TF-IDF >= 0.45 O Dice de
      content-words >= 0.30) — las parafrasis reales (TF-IDF 0.23-0.27,
      Dice 0.43-0.55) se bloquean.
  T2) El guard compara contra TODOS los comentarios previos del post
      (DedupStore ahora persiste TEXTO, no solo IDs) y termina en ABSTENER
      (None) tras una regeneracion fallida.
  T3) DedupStore.get_agent_comment_text / set_agent_comment_text /
      get_agent_comment_texts_for_post persisten el contenido cross-restart.

  T4 (regresion): replies legitimamente distintas en el mismo thread NO se
  bloquean (los ejemplos C/D del audit de gates).

Aislado con tmp_path; no publica nada; no escribe en data/ real.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

import services.reply_cap as rcap
from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps

# UUID sintetico (len > 10).
POST = "5e1f2a3b-4c5d-6e7f-8a9b-0c1d2e3f4a5b"

# Frases citadas por el operador desde el hilo de bytes: mismo argumento,
# vocabulario distinto (TF-IDF entre ellas: 0.23-0.27).
_THREAD_PHRASES = [
    "Version-aware constraints don't solve the problem—they relocate it",
    "Version-aware constraints collapse into the same trap",
    "Version-aware constraints still assume the interface is the ground truth",
]


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Aisla contadores per-post a tmp (conftest ya aisla dedup store y
    reply_history)."""
    monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json")
    monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json")
    monkeypatch.setattr(rcap, "_TOTAL_REPLIES_PER_POST_PATH", tmp_path / "total_replies_per_post.json")
    yield


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 30,
            "max_comments_per_day": 400,
            "max_comment_replies_per_cycle": 4,
            "max_feed_comments_per_post": 3,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    # La regeneracion devuelve OTRA parafrasis del mismo argumento: el fix
    # debe terminar en ABSTENER (None), no en re-frasear infinito.
    pb.llm.generate = AsyncMock(return_value=_THREAD_PHRASES[2])
    return pb


# ── T1: parafrasis contra el ULTIMO comentario del thread ───────

@pytest.mark.parametrize("i,j", [(0, 1), (1, 2), (0, 2)])
@pytest.mark.asyncio
async def test_same_thread_paraphrase_blocked_against_last_comment(i, j):
    """Nuevo reply que re-frasea el argumento del ultimo comentario nuestro
    en el MISMO post debe ser bloqueado (None). Hoy pasa limpio (RED)."""
    pb = _make_pb()
    pb._last_comment_per_thread[POST] = _THREAD_PHRASES[i]

    result = await pb._check_and_prevent_duplicate(POST, _THREAD_PHRASES[j])

    assert result is None, (
        f"RED: parafrasis del mismo argumento en el mismo thread NO fue bloqueada "
        f"(par {i},{j}: {_THREAD_PHRASES[i]!r} vs {_THREAD_PHRASES[j]!r})"
    )


# ── T2: historial fino — el comentario VIEJO no se compara ──────

@pytest.mark.asyncio
async def test_same_thread_paraphrase_blocked_against_older_comment():
    """El nuevo reply parafrasea un comentario VIEJO del thread (no el
    ultimo). El guard debe comparar contra TODOS los previos; hoy el viejo
    es invisible y pasa (RED)."""
    pb = _make_pb()
    # Ultimo comentario del thread: argumento DISTINTO.
    pb._last_comment_per_thread[POST] = "Metrics pipelines drift because schemas change silently."
    # Dos comentarios previos del thread (IDs en dedup store, textos solo
    # disponibles si el store los persiste — hoy NO los persiste).
    pb._agent_comment_ids[POST] = ["c-old-1", "c-old-2"]

    class _FakeDedupWithTexts:
        def get_agent_comment_text(self, post_id, cid):
            return _THREAD_PHRASES[0]

    pb._dedup = _FakeDedupWithTexts()

    result = await pb._check_and_prevent_duplicate(POST, _THREAD_PHRASES[1])

    assert result is None, (
        f"RED: parafrasis de un comentario VIEJO del thread no fue bloqueada: "
        f"{_THREAD_PHRASES[1]!r}"
    )


# ── T3: DedupStore no persiste TEXTO de comentarios ─────────────

def test_dedup_store_persists_comment_texts():
    """El fix debe persistir el TEXTO de nuestros comentarios por post para
    poder comparar cross-ciclo/restart. Hoy DedupStore solo guarda IDs (RED)."""
    from services.dedup_store import DedupStore

    store = DedupStore()
    assert hasattr(store, "get_agent_comment_text"), (
        "RED: DedupStore no expone get_agent_comment_text — el historial de "
        "contenido del thread no sobrevive y el guard compara contra nada"
    )
    assert hasattr(store, "set_agent_comment_text")
    assert hasattr(store, "get_agent_comment_texts_for_post")


# ── T4: regresion — replies distintas NO se bloquean ────────────

_OK_MECHANISM = (
    "Version-aware constraints break under prompt-template swaps; gate on "
    "the delta between agent behavior and environment state, reject when "
    "the deviation exceeds the observed baseline."
)
_OK_CONCEPT = "This is the same failure mode as a circuit breaker that never re-closes."


@pytest.mark.asyncio
async def test_same_thread_distinct_replies_not_blocked():
    """Dos replies legitimamente distintas en el mismo thread (mecanismo
    concreto vs analogia general) NO deben ser bloqueadas por el guard."""
    pb = _make_pb()
    pb._last_comment_per_thread[POST] = _OK_MECHANISM

    result = await pb._check_and_prevent_duplicate(POST, _OK_CONCEPT)

    assert result is not None, (
        "REGRESION: el guard bloqueo una reply legitimamente distinta "
        "(Dice ~0 entre los dos textos)"
    )
