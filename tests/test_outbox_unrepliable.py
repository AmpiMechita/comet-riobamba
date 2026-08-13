"""Tests del fix "padre borrado" (404 Parent comment not found):

- el comentario se marca unrepliable (dedup durable) y NO vuelve a la cola
- el outbox no reintenta ese error (failed determinista)
- comentarios vacios/borrados/sin id/unrepliable se filtran ANTES de generar
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.reply_cap as rcap
from services.moltbook_api_client import is_parent_not_found_404
from services.persistence import (
    enqueue_outbox,
    fetch_pending_outbox,
)
from services.reply_cap import (
    has_replied_to_comment,
    is_unrepliable_comment,
    mark_replied_to_comment,
    mark_unrepliable_comment,
)
from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


# ── Clasificador 404 de padre inexistente ──────────────────────

class TestIsParentNotFound404:
    def test_404_parent_message_positive(self):
        result = {
            "success": False, "status": 404, "id": None,
            "raw": {"statusCode": 404, "message": "Parent comment not found"},
        }
        assert is_parent_not_found_404(result) is True

    def test_404_parent_message_in_error_field(self):
        result = {"success": False, "status": 404, "error": "Parent comment not found", "raw": {}}
        assert is_parent_not_found_404(result) is True

    def test_404_other_message_negative(self):
        result = {"success": False, "status": 404, "raw": {"message": "Post not found"}}
        assert is_parent_not_found_404(result) is False

    def test_non_404_statuses_negative(self):
        for status in (400, 403, 429, 500):
            result = {"success": False, "status": status, "raw": {"message": "Parent comment not found"}}
            assert is_parent_not_found_404(result) is False, f"status {status} no es 404-parent"

    def test_non_dict_negative(self):
        assert is_parent_not_found_404(None) is False
        assert is_parent_not_found_404("error") is False


# ── Namespace unrepliable (dedup durable separado) ──────────────

class TestUnrepliableNamespace:
    def test_mark_and_check_persist(self, tmp_path):
        path = tmp_path / "unrepliable.json"
        assert is_unrepliable_comment("post-1:c-1", path) is False
        assert mark_unrepliable_comment("post-1:c-1", path) is True
        assert is_unrepliable_comment("post-1:c-1", path) is True
        assert is_unrepliable_comment("post-1:c-2", path) is False

    def test_separate_from_replied_namespace(self, tmp_path):
        upath = tmp_path / "unrepliable.json"
        rpath = tmp_path / "replied.json"
        mark_unrepliable_comment("post-1:c-1", upath)
        assert has_replied_to_comment("post-1:c-1", rpath) is False
        mark_replied_to_comment("post-1:c-1", rpath)
        assert is_unrepliable_comment("post-1:c-2", upath) is False

    def test_empty_id_noop(self):
        assert mark_unrepliable_comment("") is False
        assert is_unrepliable_comment("") is False


# ── Pre-filtro de la cola: no generar lo que no se puede publicar ──

class TestCommentQueuable:
    def test_empty_content_filtered(self):
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "   "}, "p1")
        assert (queuable, reason) == (False, "empty_content")

    def test_no_id_filtered(self):
        queuable, reason = PhaseB._comment_queuable({"content": "hola"}, "p1")
        assert (queuable, reason) == (False, "no_id")

    def test_deleted_flag_filtered(self):
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "x", "deleted": True}, "p1")
        assert (queuable, reason) == (False, "deleted")

    def test_deleted_text_marker_filtered(self):
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "[deleted]"}, "p1")
        assert (queuable, reason) == (False, "deleted")

    def test_unrepliable_filtered(self):
        mark_unrepliable_comment("p1:c1")
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "text"}, "p1")
        assert (queuable, reason) == (False, "unrepliable")

    def test_already_replied_filtered(self):
        mark_replied_to_comment("p1:c1")
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "text"}, "p1")
        assert (queuable, reason) == (False, "already_replied")

    def test_valid_comment_queuable(self):
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "real text"}, "p1")
        assert queuable is True
        assert reason == ""


# ── Helpers de PhaseB (mismo patron que test_phase_b_own_post_engagement) ──

_REPLY_TEXT = (
    "The fix is a canonical key contract: the consumer reads the same field the "
    "client normalizes, and a contract test asserts the pair stays aligned."
)


def _make_pb(max_comments_per_post=10, max_comments_per_day=15,
             max_replies_per_cycle=5, behavior_extra=None):
    behavior = {
        "max_comments_per_post": max_comments_per_post,
        "max_comments_per_day": max_comments_per_day,
        "max_comment_replies_per_cycle": max_replies_per_cycle,
        "max_feed_replies_per_day": 3,
        "delay_between_comments": 0,
    }
    if behavior_extra:
        behavior.update(behavior_extra)
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg=behavior,
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value=_REPLY_TEXT)
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "new-comment-id", "status": 201}
    pb._memory = MagicMock()
    pb._memory.get_memory.return_value = None
    return pb


@pytest.fixture
def _redirect_paths(tmp_path):
    """Redirect file paths a tmp (mismo patron que test_phase_b_own_post_engagement)."""
    import services.conversation_state as cs
    import services.dedup_store as ds
    import services.research_agenda as ra
    import phases.phase_b as pb_mod
    import services.reply_cap as rcap_mod

    orig_cs = cs.CONVERSATIONS_PATH
    orig_rep = pb_mod._REPLIED_IDS_PATH
    orig_com = pb_mod._COMMENTED_POSTS_PATH
    orig_agc = pb_mod._AGENT_COMMENT_IDS_PATH
    orig_upv = pb_mod._UPVOTED_POST_IDS_PATH
    orig_fol = pb_mod._FOLLOWED_AGENTS_PATH
    orig_rpp = rcap_mod._REPLIES_PER_POST_PATH
    orig_dedup = ds.DedupStore._default_db_path
    orig_agenda = ra.AGENDA_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    pb_mod._REPLIED_IDS_PATH = tmp_path / "replied_comment_ids.json"
    pb_mod._COMMENTED_POSTS_PATH = tmp_path / "commented_post_ids.json"
    pb_mod._AGENT_COMMENT_IDS_PATH = tmp_path / "agent_comment_ids.json"
    pb_mod._UPVOTED_POST_IDS_PATH = tmp_path / "upvoted_post_ids.json"
    pb_mod._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents.json"
    rcap_mod._REPLIES_PER_POST_PATH = tmp_path / "replies_per_post.json"
    ds.DedupStore._default_db_path = tmp_path / "comet_dedup.db"
    ra.AGENDA_PATH = tmp_path / "research_agenda.json"

    _orig_json_files = {}
    for _ns, _jpath, _fmt in ds._JSON_NAMESPACES:
        _p = Path(_jpath)
        if _p.exists():
            _orig_json_files[_jpath] = _p.read_bytes()
            _p.unlink()

    yield

    cs.CONVERSATIONS_PATH = orig_cs
    pb_mod._REPLIED_IDS_PATH = orig_rep
    pb_mod._COMMENTED_POSTS_PATH = orig_com
    pb_mod._AGENT_COMMENT_IDS_PATH = orig_agc
    pb_mod._UPVOTED_POST_IDS_PATH = orig_upv
    pb_mod._FOLLOWED_AGENTS_PATH = orig_fol
    rcap_mod._REPLIES_PER_POST_PATH = orig_rpp
    ds.DedupStore._default_db_path = orig_dedup
    ra.AGENDA_PATH = orig_agenda

    for _jpath, _data in _orig_json_files.items():
        Path(_jpath).write_bytes(_data)


# ── 404 de padre: unrepliable + SIN outbox (no quema LLM otra vez) ──

@pytest.mark.asyncio
async def test_post_own_reply_404_parent_marks_unrepliable_and_no_outbox(_redirect_paths):
    """create_comment devuelve 404 'Parent comment not found' → el comentario se
    marca unrepliable y NO se encola al outbox (determinista, no se reintenta)."""
    pb = _make_pb()
    pb.api.create_comment.return_value = {
        "success": False, "status": 404, "id": None,
        "raw": {"statusCode": 404, "message": "Parent comment not found"},
    }

    result = await pb._post_own_reply("post-1", "comment-1", "user1", "some comment text")

    assert result is not None
    assert result.get("unrepliable") is True, "el resultado debe indicar unrepliable"
    assert is_unrepliable_comment("post-1:comment-1"), "debe quedar en el namespace unrepliable"
    pending = [i for i in fetch_pending_outbox(limit=10) if i.get("kind") == "comment"]
    assert pending == [], "un 404 de padre no debe encolarse al outbox"


@pytest.mark.asyncio
async def test_post_own_reply_404_marks_unrepliable_even_after_regeneration(_redirect_paths):
    """Con _check_and_prevent_duplicate haciendo regenerar, el flujo igual llega
    a publicar y el 404 termina en unrepliable (no en outbox)."""
    pb = _make_pb()
    pb.api.create_comment.return_value = {
        "success": False, "status": 404, "id": None,
        "raw": {"statusCode": 404, "message": "Parent comment not found"},
    }

    result = await pb._post_own_reply("post-9", "comment-9", "user1", "some comment text")

    assert result is not None and result.get("unrepliable") is True
    assert is_unrepliable_comment("post-9:comment-9")
    pending = [i for i in fetch_pending_outbox(limit=10) if i.get("kind") == "comment"]
    assert pending == []


# ── Outbox: no reintenta el 404 de padre ─────────────────────────

def _make_agent(moltbook):
    from core.agent import COMETRiobambaAgent
    import config.config as _cfg

    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values={
            "phase_a_publish_enabled": False,
            "phase_b_enabled": False,
            "phase_c_enabled": False,
            "whisper_mode": False,
        }, clear=False),
    ):
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=MagicMock(),
            moltbook_client=moltbook,
        )
    ag.state = MagicMock(posts_today=0, comments_today=0)
    return ag


def _enqueue_comment(post_id="post-1", parent_id="parent-0001"):
    enqueue_outbox(kind="comment", payload={
        "post_id": post_id,
        "content": "test comment body",
        "parent_comment_id": parent_id,
    })


def _outbox_status(kind="comment"):
    import sqlite3
    import services.persistence as sp
    c = sqlite3.connect(sp.DB_PATH)
    try:
        row = c.execute("SELECT status, retry_attempt FROM outbox WHERE kind=?", (kind,)).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        c.close()


def test_comment_outbox_404_parent_marks_unrepliable_and_failed():
    """El retry del outbox clasifica el 404 de padre como failed determinista y
    ademas marca el comment como unrepliable para que no vuelva a la cola."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": False, "status": 404, "id": None,
        "raw": {"message": "Parent comment not found"},
    })
    ag = _make_agent(moltbook)
    _enqueue_comment(post_id="post-1", parent_id="parent-0001")

    published = ag._retry_comment_outbox()

    assert published == 0
    assert _outbox_status() == ("failed", 0)
    pending = [i for i in fetch_pending_outbox(limit=10) if i.get("kind") == "comment"]
    assert pending == [], "el item no debe quedar pendiente para reintentar"
    assert is_unrepliable_comment("post-1:parent-0001"), "el padre borrado debe quedar unrepliable"


# ── Pre-filtro en la cola real (antes de generar) ────────────────

@pytest.mark.asyncio
async def test_own_post_queue_filters_deleted_empty_unrepliable_before_generation(_redirect_paths):
    """La cola de own-post replies descarta borrados/vacios/unrepliable ANTES
    de llamar al LLM: solo el comentario valido genera respuesta."""
    pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
    post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
    pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
    pb.api.fetch_my_posts = MagicMock(return_value=[])
    pb.api.fetch_post_comments.return_value = [
        {"id": "c-deleted", "author": {"name": "user1"}, "content": "[deleted]", "text": "[deleted]"},
        {"id": "c-empty", "author": {"name": "user1"}, "content": "", "text": ""},
        {"author": {"name": "user1"}, "content": "no id here"},
        {"id": "c-unrepliable", "author": {"name": "user1"}, "content": "real content"},
        {"id": "c-good", "author": {"name": "user1"}, "content": "What about error handling?", "text": "What about error handling?"},
    ]
    pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
    mark_unrepliable_comment("top-12345678-aaaa-bbbb-cccc-ddddeeeeffff:c-unrepliable")
    # El clasificador de valor posterior a publicar usa el LLM (2da llamada) —
    # se aisla para medir SOLO la generacion de la respuesta.
    pb._classify_and_log_value = AsyncMock()

    await pb._execute_own_post_replies()

    # Solo c-good llego a generar: 1 llamada al LLM y 1 comentario publicado.
    assert pb.llm.generate.await_count == 1, f"se genero para comentarios filtrables: {pb.llm.generate.await_count}"
    called = [c.kwargs.get("parent_comment_id") or c.args[1]
              for c in pb.api.create_comment.call_args_list if c.kwargs or c.args]
    assert called == ["c-good"], f"se publico para comentarios filtrables: {called}"
    assert pb._stats.get("queue_prefiltered", 0) >= 3, "debe contarse cuantos se filtraron"
