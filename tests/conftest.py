import sys
from pathlib import Path

import pytest

# Agregar raíz del proyecto al path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture(autouse=True)
def _block_real_telegram(request, monkeypatch):
    """Bloquea envios reales a Telegram durante TODA la suite.

    Estrategia de 3 capas (2026-09-15):
    1. Parchea notify_model_event en la referencia LOCAL de model_cascade.
    2. Resetea el singleton ModelStatusTelegram.
    3. Parchea TelegramClient.send_message para no-op.

    EXCEPCION: si el test (o su archivo) lleva el marker
    `@pytest.mark.allow_telegram`, no se bloquea. Lo usa
    test_telegram_integration.py, que valida send_message con
    requests.post mockeado.
    """
    # Opt-out via marker
    if request.node.get_closest_marker("allow_telegram"):
        return

    # 1. Referencia local en model_cascade
    try:
        from services import model_cascade as mc
        monkeypatch.setattr(mc, "notify_model_event", lambda *a, **kw: None, raising=False)
    except Exception:
        pass

    # 2. Resetear singleton
    try:
        from services import model_status_telegram as mst
        monkeypatch.setattr(mst, "_model_status_telegram", None, raising=False)
    except Exception:
        pass

    # 3. Bloquear send_message (solo cuando el cliente esta enabled)
    try:
        from services import telegram_client as tc
        if not hasattr(tc.TelegramClient, "_orig_send_message_for_tests"):
            tc.TelegramClient._orig_send_message_for_tests = tc.TelegramClient.send_message

        def _noop_send_message(self, *a, **kw):
            return False

        monkeypatch.setattr(tc.TelegramClient, "send_message", _noop_send_message)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_persistent_state(tmp_path, monkeypatch):
    """Redirige TODOS los ficheros de estado persistentes a tmp_path."""
    try:
        import services.reply_cap as rcap
        monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json", raising=False)
        monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json", raising=False)
        monkeypatch.setattr(rcap, "_REPLIED_COMMENT_IDS_PATH", tmp_path / "replied_comment_ids_durable.json", raising=False)
        monkeypatch.setattr(rcap, "_TOTAL_REPLIES_PER_POST_PATH", tmp_path / "total_replies_per_post.json", raising=False)
        monkeypatch.setattr(rcap, "_UNREPLIABLE_IDS_PATH", tmp_path / "unrepliable_comment_ids.json", raising=False)
    except Exception:
        pass

    try:
        import services.dedup_store as ds
        monkeypatch.setattr(ds.DedupStore, "_default_db_path", tmp_path / "comet_dedup.db", raising=False)
    except Exception:
        pass

    try:
        import services.conversation_state as cs
        monkeypatch.setattr(cs, "CONVERSATIONS_PATH", tmp_path / "conversations.json", raising=False)
    except Exception:
        pass

    # FIX 2026-09-15: aislar el outbox real (comet_state.db).
    # Sin esto, tests como test_outbox_backoff.py escriben en el outbox
    # de produccion y el agente publica "T"/"B" al arrancar.
    try:
        import services.persistence as sp
        monkeypatch.setattr(sp, "DB_PATH", tmp_path / "comet_state.db", raising=False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_hours(monkeypatch):
    """Vacía los gates de horas en tests para que Phase A/B no
    dependan de la hora real del sistema. Los tests que quieran
    probar los gates los sobrescriben con monkeypatch.setitem.
    """
    try:
        import config.config as cfg
        monkeypatch.setitem(cfg.behavior_cfg, "quiet_hours", [])
        monkeypatch.setitem(cfg.behavior_cfg, "post_hours", [])
        monkeypatch.setitem(cfg.behavior_cfg, "comment_hours", [])
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_telegram_outbox(tmp_path, monkeypatch):
    """Redirige el outbox de Telegram a tmp_path para que los tests
    no ensucien el data/telegram_outbox.json real (bug 2026-09-16:
    test_telegram_integration filtraba chat_id="12345" al outbox y
    el agente intentaba reenviar cada 7s).
    """
    try:
        from services import telegram_client as tcli
        monkeypatch.setattr(tcli.TelegramClient, "OUTBOX_FILE", tmp_path / "telegram_outbox.json", raising=False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_karma_roi_db(tmp_path, monkeypatch):
    """Redirige data/karma_roi.db a tmp_path. Mismo patrón que
    T/B de Moltbook (2026-09-15) y telegram_outbox (2026-09-16):
    los tests filtraban fixtures (post_id=top-12345678-*,
    comment_id=c1/c2/new) a la DB real de producción.
    """
    try:
        import services.karma_roi_tracker as krt
        monkeypatch.setattr(krt, "DB_PATH", tmp_path / "karma_roi.db", raising=False)
        monkeypatch.setattr(krt, "JSONL_PATH", tmp_path / "karma_roi_tracker.jsonl", raising=False)
        if hasattr(krt, "KARMA_TRACKER_FILE"):
            monkeypatch.setattr(krt, "KARMA_TRACKER_FILE", tmp_path / "karma_roi_tracker.jsonl", raising=False)
    except Exception:
        pass