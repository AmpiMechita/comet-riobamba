# Runbook: Investigate Repeated Replies

## Purpose

Trace why the agent replied more than once to the same comment, or published two substantively identical replies in the same thread.

## Prerequisites

- Access to logs, traces, and state files
- PowerShell 7+

## Investigation Steps

### 1. Confirm the Incident

```powershell
# Search for duplicate skip events in the relevant timeframe
Get-Content logs/agent.log | Select-String "duplicate"
```

Zero results does _not_ mean no incident — the near-duplicate detector may not have fired if the threshold was not reached.

### 2. Find the Relevant Cycle Logs

Check the approximate time of the duplicate reply:

```powershell
# List cycle logs around the timeframe
Get-ChildItem logs/cycle_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 10
```

Read the cycle log for the cycle when the duplicate occurred:

```powershell
Get-Content logs/cycle_825.json | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d, indent=2))"
```

### 3. Trace the Decision

```powershell
# Find Phase B trace spans for the relevant date
Get-ChildItem traces/phase_b_*.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 3

# Search for the specific post_id
Get-Content traces/phase_b_20260614.jsonl | Select-String "<post_id>" | ForEach-Object { $_ | python -m json.tool }
```

If the tracer span shows `outcome: published` twice for the same `(post_id, comment_id)`, the dedup check failed.

### 4. Check Dedup State

```powershell
# Check if the comment ID was in the dedup set
python -c "
import json
with open('data/replied_comment_ids.json') as f:
    ids = json.load(f)
# Search for the specific post_id
matches = [k for k in ids if '<post_id>' in k]
print(f'Found {len(matches)} entries for post_id')
for m in matches:
    print(f'  {m}')
"
```

If the ID is missing from the set, the dedup file was not updated before the second reply was published.

### 5. Determine Root Cause — Code, State, or Deployment

#### Path A: Code Bug
- **Evidence**: Dedup check (`dedup_key in self._replied_comment_ids`) is at `phase_b.py:1419` for own posts, `line 1551` in `_post_own_reply`, and `line 2107` for debate continuations. If the tracer shows the check was reached but passed, look for logic errors.
- **What to check**: Was the dedup key computed correctly? Compare the actual key used (`f"{post_id}:{comment_id}"`) against the API response field names. Was `comment_id` `None` or missing (`"None:None"` keys)?
- **Scenarios**:

| Scenario | Evidence | Root Cause |
|----------|----------|------------|
| Dedup set NOT checked before generation | Tracer shows 2 generations for same (post_id, comment_id) pair | Code path bypassed dedup check — likely in a code branch added after the check |
| Dedup set NOT updated after first publish | First publish succeeded but `replied_comment_ids.json` unchanged | `_save_replied_comment_ids()` failed silently (line 1617); check logs for write errors |
| Comment ID format mismatch | Tracer shows dedup key `"p123:c456"` but API returns `"c456"` as integer `456` | Type mismatch between `str(comment_id)` and actual key — the dedup key `f"{post_id}:{comment_id}"` uses string interpolation, which may differ from how the API returns the ID |
| Near-duplicate detector missed | `is_near_duplicate_reply` returned False at 0.6 threshold but replies are substantively similar | Threshold too high for short replies (bigram overlap requires 60%+ word overlap) |
| State file corrupted or rolled back | `replied_comment_ids.json` truncated, from backup, or shows missing entries | File rotation or manual restore lost entries |

#### Path B: State File Corruption
- **Evidence**: `replied_comment_ids.json` contains non-UUID keys, is missing entries from today, or has `"None:None"` entries.
- **What to check**: Parse the file and look for anomalies:
  ```powershell
  python -c "
  import json
  ids = json.load(open('data/replied_comment_ids.json'))
  print(f'Total entries: {len(ids)}')
  non_uuid = [k for k in ids if not __import__('re').match(r'^[a-f0-9-]{36}:[a-f0-9-]{36}', k)]
  if non_uuid:
      print(f'Non-UUID keys: {non_uuid}')
  "
  ```
- **Root cause**: Previous incident INC-001 (non-UUID contamination). Current write paths validate UUIDs, but old corrupt entries may persist.

#### Path C: Deployment Mismatch
- **Evidence**: The code you inspected is not the code that was running. Check `health.json` version field vs actual repo state.
- **What to check**: 
  ```powershell
  git log --oneline -1
  python -c "import json; print(json.load(open('data/state/health.json')).get('version'))"
  ```
- **Root cause**: Manual deployment with different git state than expected (INC-003). No CI/CD to pin versions.

### 6. Inspect Write Log

```powershell
# Check write decisions for the relevant post_id
Get-Content data/write_log.jsonl | Select-String "<post_id>" | ForEach-Object { $_ | python -m json.tool }
```

Look for multiple `allowed` decisions for the same target. The `idempotency_key` field should be unique per interaction.

## Containment

1. **Immediate**: Add the offending `post_id:comment_id` to `data/replied_comment_ids.json` by hand to prevent further duplicates.

```powershell
python -c "
import json
with open('data/replied_comment_ids.json') as f:
    ids = json.load(f)
ids.append('<post_id>:<comment_id>')
with open('data/replied_comment_ids.json','w') as f:
    json.dump(ids, f, indent=2)
print('Added. Total entries:', len(ids))
"
```

2. **Restart**: If the agent is running and the dedup fix requires a code change, schedule a restart.

## Long-Term Fix

- Ensure dedup check runs _before_ generation, not only before publish
- Add type coercion for comment IDs (always string)
- Add a uniqueness constraint in the SQLite outbox table to prevent enqueuing duplicate replies
- Expand eval suite with cases that test ID format mismatch

## Prevention Checklist

- [ ] Dedup check runs before every generation call
- [ ] Comment IDs coerced to string before key construction
- [ ] `replied_comment_ids.json` is synced after every successful publish
- [ ] Bigram threshold is calibrated against known false negatives
