# BUILD IDENTITY — COMET-RIOBAMBA v4.3.0

> Static verification snapshot. Generated: 2026-06-14

## Expected Version

| Attribute | Value |
|-----------|-------|
| Version identifier | 4.3.0 (evolving toward v5.0) |
| Git commit | `a9c06bd` |
| Date/Time (UTC) | 2026-06-14T10:25:16+00:00 (from `health.json`) |
| Git status | **DIRTY** — 7 tracked files modified, 200+ untracked |

## Git Commit Details

```
commit a9c06bd0305e54782cf1e4762526e771e58ff8fb
feat: research_agenda con 5 topics tecnicos de investigacion
```

### Modified Tracked Files

| File | Status |
|------|--------|
| `data/research_agenda.json` | Modified |
| `phases/phase_b.py` | Modified |
| `phases/phase_c_analytics.py` | Modified |
| `services/challenge_solver.py` | Modified |
| `services/global_circuit.py` | Modified |
| `tests/test_challenge_solver.py` | Modified |
| `tests/test_phase_b_wiring.py` | Modified |

## Critical Module Checksums (SHA-256)

| Module | SHA-256 | Lines | Role |
|--------|---------|-------|------|
| `phases/phase_b.py` | `8F63FECC4AB52D4800F48260BD0774E24C5E7A7D2C802FCF8E8CAD7F30B2C4C1` | ~1759 | Community replies (own post + feed + debate), strategic upvotes & follows, semantic search, spans |
| `core/state_manager.py` | `50BEFDA1BFF610CCF58A138D97D97D8E4DA23D8DE8B0660A1EFEB05C92364FA4` | 119 | AgentState reconciliation + daily reset |
| `core/tracer.py` | `9A48D0C180CC22FB264846812DEA9BB12B15F4CBB71F693B8CC9DAB02FFD7F26` | 46 | Span context manager (used by phase_b spans) |
| `phases/phase_a_content.py` | `5BCD62CF5A0CF5EA79D643A0075D3FE7199DFE7361A67334FA75DC7214A696A7` | 583 | Content generation, validation, publication |
| `phases/phase_c_analytics.py` | `F10FE3B24CA97816B440845B2108F394C776BF2B14D0A7B8F5BC159F128B1270` | ~464 | Analytics, insight generation, CAPTCHA rate |
| `services/claim_checker.py` | `7BEB71F3900F62B7548E0E7D1B1B9DB001036BC019B00E9B8E2152585EA83E91` | 146 | Two-call LLM claim extraction + verification |
| `services/conversation_state.py` | `88D7F1200A91265E8ECE7D5EA1C2C74ACC3E4DDF63DB82E36227FF3EC69B8394` | 108 | Per-thread turn tracking, open question detection |
| `services/metrics.py` | `AA76ACCEB5C96D028775AA48EFCCE21E859139C2AA0F054C255CA17E8CCC28CA` | 182 | Daily metrics aggregation and persistence |
| `core/write_policy.py` | `EB2402748C087BDC05E7FB83AB5D33EEA77D04E6769F5796E046E41A3D81D3C1` | 391 | Content governance: editorial fit, caps, cooldown |
| `services/persistence.py` | `38F182023EEBCFC23AB8E9F25A3E69BEA6A6F3F403F0C3FF50CDEA604C03EF8E` | ~504 | SQLite state (agent_state, outbox, embeddings, flags) |
| `services/model_cascade.py` | `2340687D1033A3C9D7E5B167B3F9BC75376C1BC599E7F3862836441BBB29E4AF` | ~469 | Multi-provider LLM orchestration with circuit breakers |
| `services/global_circuit.py` | `D13509778303F3D620A31AD48A182699ECF5A5647B84447150E0EEEAC9355433` | ~269 | Global cycle control with dynamic interval |
| `core/agent.py` | `76870962DF3008E16110A250794D26A1254EB45EC7930825DA32F72A10776F35` | ~848 | Agent orchestrator: cycle loop, phase coordination, home dashboard |
| `services/self_eval.py` | `E687A050D61E14D56C973B52288F321F8C314B8CA80094CDCD0CCB5CC4C982B4` | 73 | Daily metrics (posts, comments, upvotes, follows, etc.) |
| `services/moltbook_api_client.py` | `08615D8FA558F2FD1EA2F70CF4B6FA9A5893CC15C204185BA76E39308DBF154A` | ~155 | Moltbook API HTTP client, verification support, verification_challenge span |
| `core/challenge_solver.py` | `ABDFB10EEF25AC9FBFDE5F84F38DB7E3036CA9B7E097E72045082A919B928ACB` | 49 | Verification challenge solver, LLMClientAdapter, solve_sync |
| `evals/run_evals.py` | `D40BE15AD67E4B3F4193FF1BCC395A5D78722721A2D465FADBEF6F1FF8A8C771` | 113 | Behavioral eval runner (85% threshold, 31 cases) |
| `tests/test_engagement_capabilities.py` | (see below) | 433 | Tests for home dashboard, upvotes, following, semantic search |

## State File Health

| File | Exists | Format | Notes |
|------|--------|--------|-------|
| `data/state/health.json` | Yes | JSON | `version: 4.3.0`, `cycle: 8`, `posts_today: 1`, clean |
| `data/replied_comment_ids.json` | Yes | JSON List | 3 entries, all valid UUID keys |
| `data/commented_post_ids.json` | Yes | JSON Dict | UUID keys with timestamps |
| `data/agent_comment_ids.json` | Yes | JSON Dict | Post→comment_id+timestamp |
| `data/conversations.json` | Yes | JSON | Per-thread state |
| `data/editorial_policy.json` | Yes | JSON | 12 topics, weights 0.83–0.95 |
| `data/own_post_ids.json` | Yes | JSON List | Published post IDs |
| `data/research_agenda.json` | Yes | JSON | **Modified** — uncommitted changes |
| `data/comet_state.db` | Yes | SQLite (WAL) | Backups: `.stable-*`, `.broken-*`, `.pre-*` |
| `data/performance_summary.json` | Yes | JSON | `low_relevance` always 0.0 (known P3 placeholder) |
| `data/upvoted_post_ids.json` | Yes | JSON List | Empty list on fresh start (created on first upvote) |
| `data/followed_agent_names.json` | Yes | JSON List | Empty list on fresh start (created on first follow) |
| `data/last_announcement.json` | Yes | JSON | Stores last seen Moltbook announcement ID |

## Eval Suite

| Metric | Value |
|--------|-------|
| Fixture file | `evals/fixtures/phase_b_cases.json` |
| Total cases | 19 |
| By type | feed=15, own_post=2, debate=2 |
| Required pass rate | 85% |
| Runner | `evals/run_evals.py` — imports `PhaseB` directly from `phases.phase_b` |
| CI enforcement | None (manual only) |

## v4.3.0 → Community Engagement Layer

### 4 Capabilities

| Capability | Function | Primary File |
|------------|----------|-------------|
| Home dashboard | `_check_home_dashboard()` | `core/agent.py` |
| Strategic upvotes | `_maybe_upvote()` | `phases/phase_b.py` |
| Strategic following | `_maybe_follow_author()` | `phases/phase_b.py` |
| Semantic search | `_fetch_semantic_search_posts()` | `phases/phase_b.py` |

### 3 Persisted Files

| File | Format | Owner |
|------|--------|-------|
| `data/upvoted_post_ids.json` | JSON List | `phases/phase_b.py` |
| `data/followed_agents.json` | JSON Object `{following, unfollowed}` | `phases/phase_b.py` |
| `data/last_announcement.json` | JSON Object `{last_seen_id}` | `core/agent.py` |

### 8 New Env Vars

| Env Var | Default | Effect |
|---------|---------|--------|
| `HOME_DASHBOARD_ENABLED` | `true` | Enable /home call at cycle start |
| `UPVOTES_ENABLED` | `true` | Enable strategic upvotes |
| `MAX_UPVOTES_PER_CYCLE` | `3` | Max upvotes per cycle |
| `FOLLOWING_ENABLED` | `true` | Enable strategic following |
| `MAX_FOLLOWS_PER_CYCLE` | `2` | Max follows per cycle |
| `SEMANTIC_SEARCH_ENABLED` | `true` | Enable semantic search feed complement |
| `SEMANTIC_SEARCH_MAX_QUERIES` | `2` | Max search queries per cycle |
| `SEMANTIC_SEARCH_LIMIT` | `15` | Results per query |

### Design Characteristics

- **Additive**: All four capabilities are opt-out (enabled by default).
  Disabling any reverts to pre-v4.3 behavior without side effects.
- **Fail-open**: If an API endpoint returns an error or a state file is corrupt,
  the agent logs the issue and continues. No engagement failure crashes the cycle.
- **Independent**: Each capability operates independently. Home dashboard is in
  `core/agent.py`; upvotes, follows, and semantic search are in `phases/phase_b.py`.

Maintenance: removed orphan test file tests/test_phase_b_debate_continuation.py (pre-existing, never committed, behavior partially covered by TestDebateContinuationNewEvidence in test_phase_b_wiring.py and eval cases own_debate_1/own_debate_ack_1; remaining coverage tracked in stub).

## Health Contract (from reference doc)

- `health.json` version field: verified `4.3.0`
- Config summary logged at every agent start (version, limits, mode flags)
- No external polling of `health.json`
- No CI/CD for deployment verification

## Session History

### 2026-06-15 — Span tracing, verification solver, engagement instrumentation

- **Verification system now functional**: added `LLMClientAdapter` + `solve_sync()` to `core/challenge_solver.py`; `_handle_verification()` in `services/moltbook_api_client.py` replaced broken asyncio chain with `solve_sync()`; `core/agent.py` now wires `LLMClientAdapter(self.model_cascade)` at `MoltbookAPIClient` construction time. Verification was previously always fail-open (`llm_client=None`). Now it has a real LLM adapter and is async-safe via thread isolation.
- **Tracer spans live**: `core/tracer.py` was dead code (zero imports). Now imported in `phases/phase_b.py` with 7 spans covering `execute()`, `_execute_feed_replies()`, `_execute_own_post_replies()`, `_generate_reply_for_post()`, `_generate_own_post_reply()`, `_post_own_reply()`. Traces write to `traces/phase_b_{YYYYMMDD}.jsonl`.
- **Engagement layer fully instrumented**: `_maybe_upvote()`, `_maybe_follow_author()`, `_fetch_semantic_search_posts()` in `phase_b.py` and `_check_home_dashboard()` in `agent.py` now emit spans, `send_event` calls, and `update_today_metrics()`. Four new daily metric keys added to `services/self_eval.py`: `upvotes_today`, `follows_today`, `semantic_searches_today`, `home_reads_today`.
- **Diagnosed agent_comment_ids gap**: `_load_agent_comment_ids` / `_save_agent_comment_ids` / `_execute_debate_continuations` confirmed missing but deferred — this is a new feature pipeline (not a restoration), requiring capture of comment IDs from `api.create_comment()`, persistence, and a new reply scan for others' posts. Xfail-strict stubs remain as spec.
- **Evals**: 31/31 Phase B evals pass (100%). 23/23 unit tests pass.

### 2026-06-16 — Verification span, engagement metric keys

- **Verification span**: `Span("verification_challenge")` added to `_handle_verification()` in `services/moltbook_api_client.py`. Sets `triggered=True` when `verification_required` is detected, `solved=True` when `solve_sync` returns a valid answer. Import added from `core.tracer`.
- **Engagement metric keys**: Added `upvotes_today`, `follows_today`, `semantic_searches_today`, `home_reads_today` to daily metrics dict in `services/self_eval.py`. All four engagement methods now call `update_today_metrics()`.
