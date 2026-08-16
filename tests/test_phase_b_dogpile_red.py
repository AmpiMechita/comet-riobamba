"""Tests del techo TOTAL de replies por post-raiz (backstop anti-dogpile).

Historia: estos tests nacieron RED (16/8/2026) reproduciendo el dogpile en
vivo del hilo de bytes: el agente publicaba sin tope TOTAL sumando vias con
presupuestos independientes (top-level anti-dogpile=3 + follow-ups=3 +
own-post sin cap de via). El fix agrega un contador TOTAL monotonic por post
(services/reply_cap.py) y un check SIN exenciones en _safe_publish_comment:

    AGENT_MAX_TOTAL_REPLIES_PER_POST_FOREIGN = 6  (post ajeno)
    AGENT_MAX_TOTAL_REPLIES_PER_POST_OWN     = 20 (post propio)

Test A: post AJENO  -> corta en 6 (el 7mo intento retorna None).
Test A2: post PROPIO -> corta en 20 (el 21er intento retorna None).
Test B: dedup semantico vs parafrasis reales del hilo de bytes: xfail
    documentado (el dedup por embeddings es un fix aparte, no borrar).

Aislado con tmp_path: nunca escribe en data/ real (patron fixture captcha).
"""

import pytest

import services.reply_cap as rcap
from phases.phase_b import PhaseB
from phases.phase_b.orchestrator import (
    is_semantic_duplicate_reply,
    is_near_duplicate_reply,
)
from phases.deps import PhaseBDeps

from unittest.mock import MagicMock

# UUID sintetico (len > 10 para que se apliquen los caps reales).
POST = "3e0d5b1f-9c2a-4e6b-8d7f-0a1b2c3d4e5f"

# Contenido que pasa todos los gates de _safe_publish_comment (50-500 chars,
# sin opener prohibido, sin medicion fabricada, sin ejemplo historico).
CONTENT = (
    "The version gate is the weakest link in the chain; each new release "
    "re-asserts a boundary that the runtime has already moved past, so the "
    "verification signal decays exactly when it should be strongest."
)


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Redirige contadores per-post y tracker de ejemplos a tmp (conftest ya
    aisla dedup store, reply_history y dedup durable per-comment)."""
    monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json")
    monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json")
    monkeypatch.setattr(rcap, "_TOTAL_REPLIES_PER_POST_PATH", tmp_path / "total_replies_per_post.json")
    monkeypatch.setattr(
        "services.used_examples_tracker._EXAMPLES_FILE",
        tmp_path / "used_historical_examples.json",
    )
    yield


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 30,   # valor de produccion (.env)
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
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "green-new", "status": 201}
    return pb


# ── Test A: techo total en post AJENO (FOREIGN = 6) ─────────────

def test_foreign_post_total_cap_stops_at_six():
    """3 top-level + 3 follow-ups publican (6/6); el 7mo intento —un follow-up
    que pasaria el sub-cap si el caller lo dejara— es bloqueado por el techo
    TOTAL y retorna None."""
    pb = _make_pb()
    # Post ajeno: el own_post_store no lo conoce → FOREIGN.
    pb._get_own_post_ids = lambda: set()

    # Vía 1: top-level en feed ajeno (anti-dogpile). Cap 3: el 4to se bloquea.
    top_attempts = [pb._safe_publish_comment(POST, CONTENT) for _ in range(4)]
    top_published = [r for r in top_attempts if r is not None]
    assert len(top_published) == 3, (
        f"sanity: anti-dogpile top-level debe publicar 3, publico {len(top_published)}"
    )

    # Vía 2: follow-ups enhebrados. El caller real limita en 3 por sub-cap;
    # el 4to intento debe ser cortado por el techo TOTAL (6/6) aunque el
    # caller fallara: es un backstop, no depende del caller.
    followups = []
    seventh = None
    for i in range(4):
        r = pb._safe_publish_comment(
            POST, CONTENT, parent_comment_id=f"reply-{i}", is_followup=True,
        )
        if i < 3:
            if r is not None:
                pb._increment_followups_count(POST)
                followups.append(r)
        else:
            seventh = r
    assert len(followups) == 3, (
        f"sanity: follow-ups deben publicar 3, publicaron {len(followups)}"
    )
    assert seventh is None, (
        "RED→GREEN: el 7mo reply en post ajeno debe ser bloqueado por el techo TOTAL (6/6)"
    )

    total_counter = pb._get_total_replies_for_post(POST)
    assert total_counter == 6, f"contador total debe ser 6, es {total_counter}"
    assert pb.api.create_comment.call_count == 6, (
        f"create_comment debe llamarse exactamente 6 veces, fue {pb.api.create_comment.call_count}"
    )

    print(f"[DIAG] post ajeno: total publicado = {len(top_published) + len(followups)} (6/6), "
          f"7mo intento bloqueado (None={seventh is None})")
    print(f"[DIAG] total_replies={total_counter}, replies_per_post={pb._get_replies_per_post(POST)}, "
          f"followups_per_post={pb._get_followups_count(POST)}")


def test_own_post_total_cap_stops_at_twenty():
    """Post propio (skip_anti_dogpile + own_post_store): el techo TOTAL corta
    en 20 — el 21er reply retorna None."""
    pb = _make_pb()
    pb._get_own_post_ids = lambda: {POST}

    own_attempts = [
        pb._safe_publish_comment(
            POST, CONTENT, parent_comment_id=f"own-{i}", skip_anti_dogpile=True,
        )
        for i in range(21)
    ]
    published = [r for r in own_attempts if r is not None]
    blocked = [r for r in own_attempts if r is None]

    assert len(published) == 20, (
        f"post propio debe publicar 20 replies (techo OWN), publico {len(published)}"
    )
    assert len(blocked) == 1, (
        f"el 21er reply debe ser bloqueado (return None), bloqueados={len(blocked)}"
    )

    total_counter = pb._get_total_replies_for_post(POST)
    assert total_counter == 20, f"contador total debe ser 20, es {total_counter}"
    assert pb.api.create_comment.call_count == 20, (
        f"create_comment debe llamarse exactamente 20 veces, fue {pb.api.create_comment.call_count}"
    )

    print(f"[DIAG] post propio: total publicado = {len(published)} (20/20), "
          f"21er intento bloqueado (None={len(blocked) == 1})")
    print(f"[DIAG] total_replies={total_counter}, replies_per_post={pb._get_replies_per_post(POST)}")


# ── Test B: dedup semantico vs parafrasis reales (xfail) ────────

# Frases citadas por el operador desde el hilo de bytes (16/8/2026): el mismo
# argumento ("el gate de versiones no arregla nada, solo lo mueve") con
# vocabulario distinto.
_BYTES_THREAD_PHRASES = [
    "Version-aware constraints don't solve the problem—they relocate it",
    "Version-aware constraints collapse into the same trap",
    "Version-aware constraints still assume the interface is the ground truth",
    "the real invariant is the contract between agent and environment",
]


@pytest.mark.xfail(
    strict=True,
    reason="dedup por embeddings es fix aparte: el TF-IDF actual no atrapa parafrasis",
)
def test_paraphrase_dedup_misses_same_argument():
    """Las parafrasis del hilo de bytes son el MISMO argumento y el dedup
    semantico deberia marcarlas como duplicadas. Hoy no lo hace (xfail)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    pairs = [(0, 1), (0, 2), (1, 2)]
    tfidf = TfidfVectorizer().fit_transform(_BYTES_THREAD_PHRASES)
    misses = []
    for i, j in pairs:
        sim = cosine_similarity(tfidf[i : i + 1], tfidf[j : j + 1])[0][0]
        semantic = is_semantic_duplicate_reply(_BYTES_THREAD_PHRASES[i], _BYTES_THREAD_PHRASES[j])
        near = is_near_duplicate_reply(_BYTES_THREAD_PHRASES[i], _BYTES_THREAD_PHRASES[j])
        print(f"[DIAG] par ({i},{j}) tfidf_sim={sim:.3f} semantic={semantic} near_bigram={near}")
        print(f"       A: {_BYTES_THREAD_PHRASES[i]!r}")
        print(f"       B: {_BYTES_THREAD_PHRASES[j]!r}")
        if not semantic:
            misses.append((i, j))

    assert not misses, (
        f"RED: is_semantic_duplicate_reply (TF-IDF, thr=0.72) NO detecto {len(misses)}/3 "
        f"pares de parafrasis del mismo argumento (hilo bytes): {misses}"
    )
