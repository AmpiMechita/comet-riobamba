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
def _isolate_daily_metrics(tmp_path, monkeypatch):
    """Aisla los archivos y el singleton de metricas; restaura ambos al salir."""
    import core.daily_metrics as metrics
    monkeypatch.setattr(metrics, "METRICS_DIR", tmp_path / "metrics", raising=True)
    monkeypatch.setattr(metrics, "_current_metrics", None, raising=True)


@pytest.fixture(autouse=True)
def _isolate_dynamic_persistent_globals(tmp_path, monkeypatch):
    """P-137: aisla los cuatro globals persistentes consultados dinamicamente."""
    import services.used_examples_tracker as used_examples
    import services.self_eval as self_eval
    import services.abstain_tracker as abstain_tracker
    import services.interlocutors as interlocutors

    monkeypatch.setattr(
        used_examples, "_EXAMPLES_FILE",
        tmp_path / "used_historical_examples.json", raising=True,
    )
    monkeypatch.setattr(
        self_eval, "STATE_PATH",
        tmp_path / "self_eval_state.json", raising=True,
    )
    monkeypatch.setattr(
        abstain_tracker, "ABSTAIN_RATE_PATH",
        tmp_path / "abstain_rate_today.json", raising=True,
    )
    monkeypatch.setattr(
        interlocutors, "_INTERLOCUTORS_PATH",
        tmp_path / "interlocutors.json", raising=True,
    )


@pytest.fixture(autouse=True)
def _isolate_secondary_persistent_sinks(tmp_path, monkeypatch):
    from core.memory_store import MemoryStore
    from core.claims_tracker import ClaimsTracker
    import phases.phase_b.orchestrator as orch
    import phases.phase_b as pb_pkg

    memory_init = MemoryStore.__init__
    claims_init = ClaimsTracker.__init__
    production_data = (ROOT_DIR / "data").resolve()

    def isolated_memory_init(self, db_path: str = "data/memory.db") -> None:
        if Path(db_path).resolve() == production_data / "memory.db":
            db_path = str(tmp_path / "memory.db")
        memory_init(self, db_path=db_path)

    def isolated_claims_init(self, data_dir: Path):
        if Path(data_dir).resolve() == production_data:
            data_dir = tmp_path
        claims_init(self, data_dir=data_dir)

    monkeypatch.setattr(
        MemoryStore, "__init__", isolated_memory_init, raising=True,
    )
    monkeypatch.setattr(
        ClaimsTracker, "__init__", isolated_claims_init, raising=True,
    )
    monkeypatch.setattr(
        orch, "_FEED_STALL_STATE_FILE",
        tmp_path / "phase_b_feed_stall.json", raising=True,
    )
    for name, filename in (
        ("_ADJUDICATOR_VERDICT_LOG_PATH", "adjudicator_verdicts.jsonl"), ("_REPLY_HISTORY_PATH", "reply_history.json"),
        ("_REPLIED_IDS_PATH", "replied_comment_ids.json"), ("_COMMENTED_POSTS_PATH", "commented_post_ids.json"),
        ("_AGENT_COMMENT_IDS_PATH", "agent_comment_ids.json"), ("_POST_HISTORY_GUARD_PATH", "post_history_guard.json"),
        ("_UPVOTED_POST_IDS_PATH", "upvoted_post_ids.json"), ("_FOLLOWED_AGENTS_PATH", "followed_agents.json"),
    ): monkeypatch.setattr(orch, name, tmp_path / filename, raising=True)
    for name in ("_REPLIED_IDS_PATH", "_COMMENTED_POSTS_PATH", "_AGENT_COMMENT_IDS_PATH", "_UPVOTED_POST_IDS_PATH", "_FOLLOWED_AGENTS_PATH"):
        monkeypatch.setattr(pb_pkg, name, getattr(orch, name), raising=True)


@pytest.fixture(autouse=True)
def _isolate_agent_runtime_outputs(tmp_path, monkeypatch):
    import builtins
    import core.agent as agent_mod
    agent_init = agent_mod.COMETRiobambaAgent.__init__
    real_open = builtins.open
    production_health = (ROOT_DIR / "data/state/health.json").resolve()
    production_diag = (ROOT_DIR / "data/self_diagnosis.jsonl").resolve()
    real_write_json_atomic = agent_mod._write_json_atomic
    production_announcement = (ROOT_DIR / "data/last_announcement.json").resolve()
    def isolated_agent_init(self, *args, **kwargs):
        agent_init(self, *args, **kwargs)
        if Path(self.health_file).resolve() == production_health:
            self.health_file = tmp_path / "health.json"
        self.stop_flag_file = tmp_path / "stop.flag"
        self.maintenance_flag_file = tmp_path / "maintenance.flag"
        self.write_policy.base_dir = tmp_path
        self.write_policy.log_path = tmp_path / "data" / "write_log.jsonl"
        self.write_policy.topic_index_path = tmp_path / "data" / "topic_index.json"
        self.write_policy.kill_switch_path = tmp_path / "data" / "kill_switch_state.json"
    def isolated_write_json_atomic(path, data, **kwargs):
        if Path(path).resolve() == production_announcement:
            path = tmp_path / "last_announcement.json"
        return real_write_json_atomic(path, data, **kwargs)
    def isolated_rotate_cycle_logs(self, keep=150):
        return None
    def isolated_open(file, *args, **kwargs):
        try:
            if Path(file).resolve() == production_diag:
                file = tmp_path / "self_diagnosis.jsonl"
        except (TypeError, ValueError, OSError):
            pass
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(agent_mod.COMETRiobambaAgent, "__init__", isolated_agent_init, raising=True)
    monkeypatch.setattr(agent_mod, "_write_json_atomic", isolated_write_json_atomic, raising=True)
    monkeypatch.setattr(agent_mod.COMETRiobambaAgent, "_rotate_cycle_logs", isolated_rotate_cycle_logs, raising=True)
    monkeypatch.setattr(builtins, "open", isolated_open, raising=True)

@pytest.fixture(autouse=True)
def _isolate_remaining_persistent_sinks(tmp_path, monkeypatch):
    import services.challenge_solver as cs; import services.incident_store as inc
    import core.tracer as tracer; import phases.phase_b.orchestrator as orch
    real_watchlist_load = orch.PhaseB._load_watchlist_count
    def isolated_watchlist_load(self):
        self._watchlist_count_path = tmp_path / "watchlist_count_today.json"
        return real_watchlist_load(self)
    monkeypatch.setattr(cs, "_CAPTCHA_SAMPLES_PATH", tmp_path / "captcha_samples.jsonl", raising=True)
    monkeypatch.setattr(inc, "INCIDENTS_PATH", tmp_path / "incidents.jsonl", raising=True)
    monkeypatch.setattr(tracer, "TRACES_DIR", tmp_path / "traces", raising=True)
    monkeypatch.setattr(orch.PhaseB, "_load_watchlist_count", isolated_watchlist_load, raising=True)

@pytest.fixture(autouse=True)
def _isolate_phase_c_persistent_sinks(tmp_path, monkeypatch):
    import phases.phase_c_analytics as pc; import services.roadmap as rm
    import services.self_improvement as si; import services.editorial_self_audit as esa
    import services.arxiv_topic_source as arxiv; import services.topic_performance_refresh as tpr
    import services.proposal_applier as pa; import services.reply_feedback as rf
    import services.energy_intel_telegram as eit; import services.research_agenda as ra
    real_path, phase_c_init, strategy_cls = Path, pc.PhaseCAnalytics.__init__, pc.StrategyState
    redirects={"exports/social_content":tmp_path/"exports"/"social_content","data/project_ideas.jsonl":tmp_path/"project_ideas.jsonl","data/claims_tracker.json":tmp_path/"claims_tracker.json"}
    def isolated_path(*parts):
        q=real_path(*parts); return redirects.get(str(q).replace("\\","/"),q)
    def isolated_init(self,*args,**kwargs):
        phase_c_init(self,*args,**kwargs); self.state_file=tmp_path/"phase_c_state.json"
    def isolated_strategy_state(path=None):
        return strategy_cls(path if path is not None else tmp_path/"strategy_state.json")
    monkeypatch.setattr(pc,"Path",isolated_path,raising=True); monkeypatch.setattr(pc.PhaseCAnalytics,"__init__",isolated_init,raising=True)
    monkeypatch.setattr(pc,"StrategyState",isolated_strategy_state,raising=True)
    patches=((ra,"AGENDA_PATH",tmp_path/"research_agenda.json"),(ra,"ARCHIVE_PATH",tmp_path/"research_agenda_archive.json"),(ra,"PRUNE_STATE_PATH",tmp_path/"prune_agenda_last_run.json"),(rm,"DEFAULT_ROADMAP_PATH",tmp_path/"topic_roadmap.json"),(rm,"PUBLISHED_LOG_PATH",tmp_path/"published_posts.json"),(si,"SELF_IMPROVEMENT_LOG_PATH",tmp_path/"self_improvement_log.jsonl"),(esa,"_STATE_PATH",str(tmp_path/"editorial_self_audit.json")),(esa,"_POSTS_STORE",str(tmp_path/"published_posts.json")),(esa,"_VOTES_LOG",str(tmp_path/"comment_votes.jsonl")),(arxiv,"REFRESH_STATE_PATH",tmp_path/"arxiv_refresh_last_run.json"),(tpr,"DATA_PATH",tmp_path/"topic_performance.jsonl"),(tpr,"REFRESH_STATE_PATH",tmp_path/"topic_performance_refresh_last_run.json"),(pa,"OVERLAY_PATH",tmp_path/"auto_applied_config.json"),(pa,"APPLY_LOG_PATH",tmp_path/"proposal_apply_log.jsonl"),(rf,"DUAL_SCORE_LOG",tmp_path/"dual_scores.jsonl"),(rf,"STRATEGY_HINT_FILE",tmp_path/"reply_strategy_hint.json"),(eit,"_LAST_RUN_FILE",tmp_path/"last_energy_intel_run.txt"),(eit,"_WEEKLY_DIGEST_STATE",tmp_path/"energy_weekly_digest_last.json"))
    for mod,name,value in patches: monkeypatch.setattr(mod,name,value,raising=True)

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

    import services.dedup_store as ds
    monkeypatch.setattr(ds.DedupStore, "_default_db_path", tmp_path / "comet_dedup.db", raising=True)
    monkeypatch.setattr(
        ds, "_JSON_NAMESPACES",
        [(namespace, str(tmp_path / Path(json_path).name), fmt)
         for namespace, json_path, fmt in ds._JSON_NAMESPACES],
        raising=True,
    )

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
