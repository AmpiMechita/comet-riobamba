# COMET-RIOBAMBA — Agent Guidance

## Run

| Task | Command |
|------|---------|
| Dev | `python run_agent.py` |
| Prod | `.\run-prod.ps1` |
| Stop (graceful) | `New-Item data/stop.flag` |
| All tests | `pytest tests/ -q` |
| Single test | `pytest tests/test_phase_b_dedup_limits.py -v` |
| Daily report | `python -m scripts.print_daily_report` |
| Historical metrics | `python -m scripts.metrics_last_n_days` |

## Architecture

- **Entrypoint:** `run_agent.py` → `core.agent.main()`, **not** `agent.py` at root (that file does not exist).
- **Not a standard package.** No `pyproject.toml`, `setup.py`, or `setup.cfg`. Dependencies: `python-dotenv`, `requests`, `pyyaml`, `pytest`.
- **State persistence:** Two SQLite databases: `data/comet_state.db` (agent_state, outbox) via `services/persistence.py`, and `data/comet_dedup.db` (Phase B dedup sets/dicts) via `services/dedup_store.py`.
- **Model cascade:** `services/model_cascade.py` — providers tried in order: `ollama_local` → `tier_opus` → `tier_sonnet` → `tier_haiku` → `openrouter` → `cerebras` → `ollama_cloud`. Circuit breaker per provider.
- **Phase B** is monolithic (`phases/phase_b.py`). **Phase C** is split: `phases/phase_c_analytics.py` + `phases/engagement/` sub-package.

## Critical Toggles

- **Graceful stop (no OS signals):** create the file `data/stop.flag` (e.g. `New-Item data/stop.flag`). The agent detects it on its next check (max 1s latency) and shuts down cleanly, including final state save. The flag is auto-deleted so it does not linger for the next startup. Preferred on Windows, where sending SIGINT/CTRL_BREAK to a background child process is unreliable.
- **Whisper mode** (`config/config.py` or env `AGENT_WHISPER_MODE=1`): when True, all Moltbook API calls are simulated. Used for lab/dev. Toggle via env var or editing `config/config.py` line 71.
- **Auto-pause:** after 3 consecutive post failures the agent pauses itself (`behavior_cfg["auto_pause_after_failures"]`).
- **Rate limiter:** token bucket in `MoltbookAPIClient`, 1 write per 150s default.

## File Conventions

- **Never modify** `.bak`, `.backup`, `.broken-*`, `.pre-*`, `.bak-*` files. These are historical snapshots (dozens exist across `core/`, `phases/`, `services/`, `config/`).
- **Never commit** `.env` (contains real API keys — already in `.gitignore`).
- **Phase A** rejects non-English content (Spanish keyword detection + `_is_mostly_english()` check).
- **Phase B cold start:** lower relevance threshold until agent has published ≥10 posts (`COLD_START_POST_THRESHOLD`).

## Testing & Quality

- No CI/CD pipelines, no linter config, no type checker config. `pytest` runs with defaults.
- 28 test files, ~78 tests total. No external services required for tests.

## Existing Context

- `CLAUDE.md` covers team conventions, stack, and LLM model recommendations.
- `README.md` covers env vars and quick start.
- `ARCHITECTURE.md` documents the v5.0 design.
