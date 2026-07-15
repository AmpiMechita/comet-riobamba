# Runbook: Investigate Upvote / Follow / Semantic Search Anomalies

## Purpose

Diagnose unexpected behavior in the v4.3.0 community engagement layer: upvote loops,
indiscriminate following, and semantic search noise.

## Prerequisites

- Access to `logs/agent.log`, `data/upvoted_post_ids.json`, `data/followed_agents.json`
- PowerShell 7+
- Python 3.x

---

## Path A: Upvote Anomaly (too many upvotes, upvotes on low-quality posts)

### Step A1 — Check cycle summary for upvote count

```powershell
Select-String -Path "logs/agent.log" -Pattern "upvotes" -SimpleMatch | Select-Object -Last 20
```

**Expected:** Upvote count is <= `MAX_UPVOTES_PER_CYCLE` (default 3) per cycle.
**If elevated:** The agent is upvoting aggressively. Proceed to A2.

### Step A2 — Inspect upvoted post IDs

```powershell
python -c "
import json
data = json.load(open('data/upvoted_post_ids.json'))
print(f'Total upvoted posts: {len(data)}')
print(f'Last 10: {list(data)[-10:]}')
"
```

**Look for:** A single post ID being upvoted multiple times (should not happen due
to dedup). A large number of upvotes on posts from the same author.

### Step A3 — Check which value levels triggered upvotes

The upvote decision is driven by `_classify_topic_value()`. If the classifier
drifted, posts classified as STANDARD/HIGH_VALUE may not warrant upvotes.

```powershell
python -c "
from phases.phase_b import PhaseB
# Simulate classification for recent skipped posts
# (replace with actual post body from logs)
sample = 'What is the best API for this task?'
cls = PhaseB._classify_topic_value(sample, [])
print(f'Sample classification: {cls}')
print('TRIVIAL → skip upvote; STANDARD/HIGH_VALUE → upvote eligible')
"
```

### Step A4 — Check classifier drift

Compare classifications over time. If the classifier shifted from producing
mostly TRIVIAL/STANDARD to mostly STANDARD/HIGH_VALUE, upvote volume will
increase.

```powershell
python -c "
import json, glob, collections
# Scan cycle logs for value classification distribution
# (cycle logs at logs/cycle_*.json)
files = sorted(glob.glob('logs/cycle_*.json'))[-20:]
counts = collections.Counter()
for f in files:
    try:
        data = json.load(open(f))
        for entry in data:
            if 'value_level' in entry:
                counts[entry['value_level']] += 1
    except: pass
print('Value level distribution (last 20 cycles):')
for k, v in counts.most_common():
    print(f'  {k}: {v}')
"
```

### Recovery A — Reset upvote state

If the upvote store is corrupted or contains bad entries:

```powershell
# Upvotes are idempotent — safe to delete and let the agent rebuild
Remove-Item -Path "data/upvoted_post_ids.json" -WhatIf
# Remove -WhatIf to execute
```

Or increase the upvote cap if the volume is intentional:

```powershell
# Check current env value
python -c "import os; print(os.getenv('MAX_UPVOTES_PER_CYCLE', '3'))"
# Set in .env: MAX_UPVOTES_PER_CYCLE=5
```

---

## Path B: Follow Anomaly (following too many agents, following low-value agents)

### Step B1 — Check cycle summary for follow count

```powershell
Select-String -Path "logs/agent.log" -Pattern "follow" -SimpleMatch | Select-Object -Last 20
```

**Expected:** Follow count is <= `MAX_FOLLOWS_PER_CYCLE` (default 2) per cycle.
**If elevated:** Proceed to B2.

### Step B2 — Inspect followed agents

```powershell
python -c "
import json
data = json.load(open('data/followed_agents.json'))
following = data.get('following', data if isinstance(data, list) else [])
unfollowed = data.get('unfollowed', [])
print(f'Following: {len(following)} agents')
print(f'Unfollowed: {len(unfollowed)} agents')
if following:
    print(f'Last 10 followed: {following[-10:]}')
"
```

### Step B3 — Check which comments triggered follows

Following is triggered in `_process_own_post()` when a comment's value is not
"general". Check recent own-post comments and their classifications.

```powershell
python -c "
from phases.phase_b import PhaseB

# Simulate comment classification
samples = [
    ('How do you handle rate limiting?', 'non_general'),
    ('Thanks for the explanation', 'general'),
    ('But what about observability overhead?', 'non_general'),
]
for text, expected_value in samples:
    from phases.phase_b import PhaseB
    # _classify_comment_value is not a static method;
    # this is a proxy check. In production the follow
    # decision uses the comment value from the pipeline.
    print(f'Comment: {text[:50]}...')
    print(f'  Expected: {expected_value}')
"
```

### Step B4 — Check same-author follow frequency

```powershell
python -c "
import json
data = json.load(open('data/followed_agents.json'))
following = data.get('following', data if isinstance(data, list) else [])
from collections import Counter
# Count per-agent (if multiple entries per agent possible)
print(f'Unique followed: {len(set(following))}')
print(f'Total follow events: {len(following)}')
"
```

### Recovery B — Reset follow state

```powershell
# Follows are idempotent — safe to delete
Remove-Item -Path "data/followed_agents.json" -WhatIf
# Remove -WhatIf to execute
```

Or tighten the follow gate:

```powershell
# Reduce max follows per cycle
# Set in .env: MAX_FOLLOWS_PER_CYCLE=1
```

---

## Path C: Semantic Search Noise (irrelevant results injected into feed)

### Step C1 — Check semantic search usage in cycle summary

```powershell
Select-String -Path "logs/agent.log" -Pattern "semantic|search" -SimpleMatch | Select-Object -Last 20
```

**Expected:** Semantic search runs when `SEMANTIC_SEARCH_ENABLED=true` (default).
Search results are a supplement to the feed, not the primary source.

### Step C2 — Check current search queries

```powershell
python -c "
import json, os

# Check research agenda topics (primary source)
try:
    agenda = json.load(open('data/research_agenda.json'))
    topics = agenda.get('pending_topics', agenda.get('topics', []))
    print(f'Research agenda topics: {len(topics)}')
    if topics:
        print(f'  Sample: {topics[:3]}')
except Exception as e:
    print(f'Research agenda: {e}')

# Check roadmap fallback
try:
    roadmap = json.load(open('data/topic_roadmap.json'))
    print(f'Roadmap entries: {len(roadmap)}')
except Exception as e:
    print(f'Roadmap: {e}')

# Check env fallback
queries = os.getenv('SEMANTIC_SEARCH_QUERIES', '')
print(f'Env query fallback: \"{queries}\"')
"
```

### Step C3 — Check query volume

```powershell
python -c "
import os
max_q = int(os.getenv('SEMANTIC_SEARCH_MAX_QUERIES', '2'))
limit = int(os.getenv('SEMANTIC_SEARCH_LIMIT', '15'))
print(f'Max queries per cycle: {max_q}')
print(f'Max results per query: {limit}')
print(f'Max total candidates: {max_q * limit}')
print(f'Note: results are deduplicated and submolts-filtered')
"
```

Too many queries + too many results can increase LLM processing load and API
costs. If the research agenda has 10+ pending topics, `SEMANTIC_SEARCH_MAX_QUERIES`
(default 2) caps the actual queries, but the query source may still select poorly
relevant topics.

### Step C4 — Detect irrelevance drift

```powershell
python -c "
import json, glob, collections

# Score distribution from cycle logs
files = sorted(glob.glob('logs/cycle_*.json'))[-20:]
scores = []
for f in files:
    try:
        data = json.load(open(f))
        for entry in data:
            if 'relevance_score' in entry:
                scores.append(entry['relevance_score'])
    except: pass

if scores:
    avg = sum(scores) / len(scores)
    print(f'Avg relevance score (last 20 cycles): {avg:.2f}')
    print(f'  Scores below threshold (4.0): {sum(1 for s in scores if s < 4)}')
    print(f'  Scores above threshold: {sum(1 for s in scores if s >= 4)}')
else:
    print('No relevance scores found in cycle logs')
"
```

A sustained drop in average relevance score may indicate semantic search is
injecting poorly matching posts, or the feed quality has degraded.

### Recovery C — Disable or tune semantic search

```powershell
# Disable temporarily
# Set in .env: SEMANTIC_SEARCH_ENABLED=false

# Reduce query volume
# Set in .env: SEMANTIC_SEARCH_MAX_QUERIES=1
# Set in .env: SEMANTIC_SEARCH_LIMIT=5
```

Or clear the research agenda to stop query generation:

```powershell
# Backup and clear pending topics
Copy-Item "data/research_agenda.json" "data/research_agenda.json.bak"
python -c "
import json
data = json.load(open('data/research_agenda.json'))
data['pending_topics'] = []
json.dump(data, open('data/research_agenda.json', 'w'))
print('Cleared pending topics')
"
```

---

## Cross-Cutting: Check All Engagement State Files

```powershell
python -c "
import json, os
files = {
    'data/upvoted_post_ids.json': 'list',
    'data/followed_agents.json': 'dict',
    'data/last_announcement.json': 'dict',
}
for fpath, expected_type in files.items():
    if not os.path.exists(fpath):
        print(f'{fpath}: does not exist (first use — OK)')
        continue
    try:
        data = json.load(open(fpath))
        actual = type(data).__name__
        ok = actual.lower().startswith(expected_type)
        print(f'{fpath}: {actual} — {\"OK\" if ok else \"UNEXPECTED TYPE\"}')
    except Exception as e:
        print(f'{fpath}: PARSE ERROR — {e}')
"
```

## Verification After Recovery

1. Restart the agent or run a single Phase B pass
2. Observe cycle summary for upvote/follow/search counts
3. Run `python evals/run_evals.py` to confirm behavioral contract holds
4. Check `logs/agent.log` for ERROR-level messages related to engagement
