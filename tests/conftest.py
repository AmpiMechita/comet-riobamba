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
        import services.karma_updater as ku
        monkeypatch.setattr(ku, "STATE_PATH", tmp_path / "karma_updater_last_run.json", raising=False)
    except Exception:
        pass

@pytest.fixture(autouse=True)
def _isolate_phase_a_jsonl_logs(tmp_path, monkeypatch):
    """Redirige los JSONL de Phase A a tmp_path.

    FIX 2026-09-20: test suite filtraba 637 bytes a
    data/generation_attempts.jsonl por ciclo de test
    (patron: datetime mockeado a 2026-07-22 + _log_generation_attempt
    ejecutado sin monkeypatch del path). Mismo patron que los fixes
    previos de comet_state.db (2026-09-15), telegram_outbox (2026-09-16)
    y karma_roi.db (2026-09-16).

    Sin esta fixture, cada corrida de pytest contamina las metricas
    de produccion con entries falsas (ts=2026-07-22T12:00:00,
    run_id=unknown)."""
    try:
        import phases.phase_a_content as pac
        monkeypatch.setattr(
            pac, "_GENERATION_ATTEMPTS_LOG",
            tmp_path / "generation_attempts.jsonl", raising=False,
        )
        monkeypatch.setattr(
            pac, "_REJECTED_POSTS_LOG",
            tmp_path / "rejected_posts.jsonl", raising=False,
        )
        monkeypatch.setattr(
            pac, "_FATIGUE_STORE",
            tmp_path / "published_posts.json", raising=False,
        )
        monkeypatch.setattr(
            pac, "_TOPIC_COOLDOWN_PATH",
            tmp_path / "phase_a_topic_cooldown.json", raising=False,
        )
        monkeypatch.setattr(
            pac, "_TOPIC_HISTORY_FILE",
            tmp_path / "topic_history.json", raising=False,
        )
    except Exception:
        pass

    try:
        import services.dual_scoring as ds
        monkeypatch.setattr(
            ds, "DUAL_SCORE_LOG",
            tmp_path / "dual_scores.jsonl", raising=False,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_topic_state(tmp_path, monkeypatch):
    """FIX P-045 2026-09-24: aisla topic_evolution_state y topic_matrix en tmp_path."""
    try:
        import services.topic_evolution as te
        monkeypatch.setattr(te, "EVOLUTION_STATE_FILE",
                            tmp_path / "topic_evolution_state.json", raising=False)
    except Exception:
        pass
    try:
        import phases.phase_a_content as pac
        import config.topic_matrix as ctm
        _ol, _os = ctm.load_topic_matrix, ctm.save_topic_matrix
        _mp = tmp_path / "topic_matrix_state.json"
        monkeypatch.setattr(pac, "load_topic_matrix", lambda _p: _ol(_mp), raising=False)
        monkeypatch.setattr(pac, "save_topic_matrix", lambda m, _p: _os(m, _mp), raising=False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_pause_state(tmp_path, monkeypatch):
    """FIX p134 (2026-09-30): aisla data/pause.flag + recheckers.

    Sin esto, cualquier test que llame a add_reason/remove_reason
    escribe el pause.flag REAL y pausa al agente en produccion.
    Mismo patron que telegram_outbox (2026-09-16) y karma_roi.db.
    """
    try:
        import services.pause_controller as pc
        monkeypatch.setattr(pc, "PAUSE_FILE", tmp_path / "pause.flag", raising=False)
        monkeypatch.setattr(pc, "_recheckers", {}, raising=False)
    except Exception:
        pass
