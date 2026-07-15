# ADR-001: System Behavioral Invariants

## Status

Accepted (2026-06-14)

## Context

COMET-RIOBAMBA operates as an autonomous agent with no human in the loop for extended periods. Without explicit, testable invariants, the system can drift into undesired states: repeated replies, topic flooding, silent skips, and untraceable decisions.

Previous incidents (invalid IDs, repeated replies, cold-start counter drift) demonstrate that implicit conventions are insufficient. Explicit contracts are needed that are:
- Machine-testable (enforced in code or eval)
- Observable (evidence emitted for every decision)
- Stable across versions (changes require eval update)

## Decision

The following six invariants are adopted as non-negotiable engineering contracts. Each has a defined enforcement mechanism and evidence requirement.

## Invariants

### I1: One Reply Per Comment (Unless Real Debate Continuation)

**Contract**: For every `(post_id, comment_id)` pair, at most one reply is published.

**Rationale**: Prevents the most common and most visible failure mode — duplicate replies.

**Enforcement (two-layer with ordering)**:
- **Layer 1 (ID-level, BEFORE generation)**: `dedup_key in self._replied_comment_ids` at `phase_b.py:1551` — a set membership check, cheap & fast
- **Layer 2 (content-level, AFTER generation, BEFORE publish)**: `is_near_duplicate_reply()` at 0.6 bigram threshold (`phase_b.py:181-205`) with auto-regeneration on match (`_check_and_prevent_duplicate`, `phase_b.py:665-722`)
- **Layer 3 (content-level, blocking)**: Claim checker (`services/claim_checker.py`) rejects off-topic replies with score < 0.6 before publish. Fail-open on LLM error (returns `on_topic: True`) — see F7 in Failure Taxonomy

**Exception**: `conversation_state.can_continue_thread()` returns `True` only when:
- Thread is not closed
- `MAX_TURNS_PER_THREAD` (4) has not been reached
- The user's latest comment contains a direct question to the agent

**Evidence**: `phase_b_duplicate_skip` event + tracer span + entry in `replied_comment_ids.json`

**Test**: `tests/test_phase_b_dedup_limits.py`, `evals/fixtures/phase_b_cases.json` (debate cases)

---

### I2: No Topic-Level Repetition Inside 24-Hour Window

**Contract**: The same `topic_key` must not appear in two posts within `topic_cooldown_hours` (default 24h). The same title must not appear within `exact_title_cooldown_hours` (default 72h).

**Rationale**: Avoids the agent publishing substantively similar content within a short window, which degrades perceived value and wastes the daily post budget.

**Enforcement**:
- `WritePolicyEngine._topic_recently_used()` checks `data/topic_index.json`
- `WritePolicyEngine._is_similar_to_recent()` checks content similarity at 85% threshold
- SHA-256 text hash dedup via SQLite `post_embeddings` table (7-day window)

**Evidence**: `write_log.jsonl` entry with reason `topic_cooldown_active`, `exact_title_cooldown_active`, or `similar_content_recently_published`

**Test**: `tests/test_daily_post_limit.py`, manual inspect of `write_log.jsonl`

---

### I3: No Publishing Without Traceability

**Contract**: Every publish (post or comment) must leave at least one traceable artifact before the API call is made.

**Rationale**: Without traceability, it is impossible to audit agent behavior, verify quotas, or debug incidents. A publish that vanishes from the record is indistinguishable from a ghost action.

**Enforcement**:
- Write policy engine logs decision (`write_log.jsonl`) before execution
- Tracer creates span before generation
- Observability event emitted after publish
- Cycle summary logged to `logs/cycle_N.json`

**Evidence**: For every successful publish, at minimum: `write_log.jsonl` entry + tracer span OR observability event.

**Test**: Manual audit of `logs/cycle_N.json` and `write_log.jsonl` correlation.

---

### I4: No Production Behavior Change Without Eval Visibility

**Contract**: Changes to relevance scoring, dedup logic, guardrail parameters, or prompting strategy must be reflected in the eval suite before deployment.

**Rationale**: Behavioral changes are subtle and easy to miss without regression testing. The eval suite is the behavioral contract.

**Enforcement**: Process-level (CI gate). `python evals/run_evals.py` must pass >= 85%.

**Evidence**: Eval suite stdout output. Exit code 1 on failure.

**Test**: `evals/fixtures/phase_b_cases.json` must be updated when behavior changes.

---

### I5: No Feed-Reply Activity if Own Comments Are Pending

**Contract**: Phase B must exhaust own-post comment replies before considering feed replies in the same pass.

**Rationale**: The agent's primary social contract is to respond to people who engage with its content. Feed engagement is secondary.

**Enforcement**: `PhaseB.execute()` calls `_execute_own_post_replies()` first. `_execute_feed_replies()` only runs if cycle budget remains.

**Evidence**: Tracer spans distinguish own-post vs feed-reply phases.

**Test**: `tests/test_phase_b_wiring.py`

---

### I6: Sequential Phase Execution Within a Cycle

**Contract**: Phase C must never run before Phase B completes. Phase B must never run before Phase A (or its skip) completes.

**Rationale**: Phase C consumes the research agenda that Phase B may have updated. Phase B may reference content generated by Phase A. Interleaving creates race conditions.

**Enforcement**: Sequential `await` calls in `_run_cycle()`. `phase_error_boundary` decorator wraps each phase individually.

**Evidence**: `logs/cycle_N.json` reflects sequential order.

**Test**: `core/agent.py` code structure (structural invariant).

## Consequences

### Positive
- Clear engineering contracts for new contributors
- Observable violations (every invariant emits machine-readable evidence)
- Eval suite explicitly linked to behavioral requirements
- Incident postmortems can reference specific invariants

### Negative
- Some invariants (I4, I6) are enforced by process/code structure rather than tests
- I3 requires audit discipline to verify
- Invariants must be maintained as the system evolves

## Notes

- These invariants should be reviewed when the Phase B reply policy or Phase A generation pipeline changes.
- New invariants should be added via ADR with the same structure.
- Violation of any invariant triggers an incident process.
