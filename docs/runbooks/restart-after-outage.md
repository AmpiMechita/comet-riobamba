# Runbook: Restart After Outage

## Purpose

Verify state consistency, code version, and environment health before restarting the COMET-RIOBAMBA agent after an unplanned stop or crash.

## Prerequisites

- Access to the repository root (`C:\comet-riobamba-v31`)
- `.env` file with valid credentials
- PowerShell 7+

## Pre-Restart Checklist

Run these checks **before** any restart attempt. Each item has a pass/fail criterion and an escalation action.

### C1: Git Status Clean (or Diff Explicitly Listed)

```powershell
git status --porcelain
```

**Expected:** Output is empty (no modified tracked files) OR all modified files are intentionally part of this deployment and documented in the deploy note.

**If fails:** Review `git diff` for each modified file. If unmodified files are changed accidentally, `git checkout -- <file>` to restore. Document intentional changes in the deploy note.

```powershell
git diff --stat
```

### C2: BUILD_IDENTITY.md Matches Current Commit

```powershell
# Verify commit hash matches
$expected = "a9c06bd"
$actual = git rev-parse --short HEAD
if ($actual -ne $expected) {
    Write-Warning "Commit mismatch: expected $expected, got $actual"
    Write-Host "Update docs/BUILD_IDENTITY.md before proceeding" -ForegroundColor Red
} else {
    Write-Host "Commit OK: $actual" -ForegroundColor Green
}
```

**Expected:** `$actual` matches the commit hash in `docs/BUILD_IDENTITY.md`.

**If fails:** Either update BUILD_IDENTITY.md with the new hash and checksums, or checkout the expected commit.

### C3: Critical Module Checksums Match BUILD_IDENTITY.md

```powershell
$checksums = @{
    "phases/phase_b.py" = "23E0DDF76BB0CDA1C3A1BED257BCF3CFFE9EFF457535D8B7B214145997117AD9"
    "core/state_manager.py" = "50BEFDA1BFF610CCF58A138D97D97D8E4DA23D8DE8B0660A1EFEB05C92364FA4"
    "core/tracer.py" = "9A48D0C180CC22FB264846812DEA9BB12B15F4CBB71F693B8CC9DAB02FFD7F26"
    "phases/phase_a_content.py" = "5BCD62CF5A0CF5EA79D643A0075D3FE7199DFE7361A67334FA75DC7214A696A7"
    "phases/phase_c_analytics.py" = "31286E1AE73D22C6C9F8140EBBF328074DADC5E2CA3AE074ABA51AFA45D08927"
}
$all_ok = $true
foreach ($file in $checksums.Keys) {
    $actual = (Get-FileHash -Path "C:\comet-riobamba-v31\$file" -Algorithm SHA256).Hash
    if ($actual -ne $checksums[$file]) {
        Write-Warning "CHECKSUM MISMATCH: $file"
        Write-Host "  Expected: $($checksums[$file])"
        Write-Host "  Actual:   $actual"
        $all_ok = $false
    }
}
if ($all_ok) { Write-Host "All checksums OK" -ForegroundColor Green }
```

**Expected:** All checksums match. A mismatch means the module has changed since BUILD_IDENTITY.md was generated.

**If fails:** Recompute checksums with `Get-FileHash` and update BUILD_IDENTITY.md. Review `git diff` for the changed file.

### C4: Critical State Files Exist and Are Parseable

```powershell
$required_files = @(
    "data/replied_comment_ids.json",
    "data/commented_post_ids.json",
    "data/agent_comment_ids.json",
    "data/state/health.json",
    "data/comet_state.db",
    "data/own_post_ids.json",
    "data/research_agenda.json",
    "data/editorial_policy.json"
)
foreach ($f in $required_files) {
    $path = "C:\comet-riobamba-v31\$f"
    if (-not (Test-Path $path)) {
        Write-Warning "MISSING: $f"
    } else {
        Write-Host "OK: $f" -ForegroundColor Green
    }
}
```

```powershell
# Verify each JSON file parses correctly
python -c "
import json, os, sys
files = ['data/replied_comment_ids.json','data/commented_post_ids.json',
         'data/agent_comment_ids.json','data/state/health.json',
         'data/own_post_ids.json','data/research_agenda.json',
         'data/editorial_policy.json']
errors = []
for f in files:
    try:
        with open(os.path.join(os.getcwd(), f)) as fh:
            json.load(fh)
    except Exception as e:
        errors.append(f'{f}: {e}')
if errors:
    for e in errors: print(f'PARSE ERROR: {e}')
    sys.exit(1)
else:
    print('All JSON files parse OK')
"
```

**Expected:** All files exist and parse as valid JSON.

**If fails:** Restore from backup (`data/archive/`, `*.stable-*`, `*.pre-*`). For `comet_state.db`, check `.broken-*` and `.stable-*` backups. **Never create state files from scratch unless you confirm the agent has zero published content today.**

### C5: UUID-Guarded Stores Contain Only Valid UUIDs

```powershell
python -c "
import json, re, sys
uuid_pat = re.compile(r'^[0-9a-f-]{36}$')
files = {
    'data/replied_comment_ids.json': lambda d: [k for k in d if ':' in str(k)],
    'data/commented_post_ids.json': lambda d: list(d.keys()) if isinstance(d, dict) else [],
    'data/agent_comment_ids.json': lambda d: list(d.keys()) if isinstance(d, dict) else [],
}
errors = []
for fname, key_fn in files.items():
    try:
        data = json.load(open(fname))
        keys = key_fn(data)
        # Extract UUID part before ':' for replied_comment_ids
        for k in keys:
            parts = str(k).split(':')
            for p in parts:
                if not uuid_pat.match(p) and len(p) == 36:
                    errors.append(f'{fname}: non-UUID key {k}')
    except Exception as e:
        errors.append(f'{fname}: {e}')
if errors:
    for e in errors: print(f'UUID ERROR: {e}')
    sys.exit(1)
else:
    print('All UUID stores clean')
"
```

**Expected:** No non-UUID keys found in any state store known to have been affected by INC-001.

**If fails:** Manually inspect and remove invalid entries. Reference `docs/COMET-RIOBAMBA_REFERENCE.md` section P1 for known patterns.

### C6: Evals Pass at Documented Threshold

```powershell
python evals/run_evals.py
```

**Expected:** Output shows `Phase B Eval Results: N/N passed (0 failed)` with pass rate >= 85%. Exit code is 0.

**If fails:** If pass rate is below 85%, check `evals/fixtures/phase_b_cases.json` for recent changes. If the code intentionally changed behavior, update the fixtures. If not, investigate which behavioral contract was broken. **Do not restart until evals pass or the failure is explicitly documented and accepted in the deploy note.**

### C7: Verify health.json Version Field

```powershell
python -c "
import json
h = json.load(open('data/state/health.json'))
expected = '4.3.0'
actual = h.get('version', 'unknown')
if actual != expected:
    print(f'VERSION MISMATCH: state has {actual}, code is {expected}')
    exit(1)
print(f'Version OK: {actual}')
print(f'Cycle: {h.get(\"cycle\")}, posts_today: {h.get(\"posts_today\")}')
"
```

**Expected:** `health.json` version matches the code version (4.3.0).

**If fails:** This indicates the state file was written by a different code version. Check git log and ensure you are deploying the correct version.

### C9: Engagement State Stores Parse Correctly

```powershell
python -c "
import json, os, sys
files = ['data/upvoted_post_ids.json', 'data/followed_agents.json', 'data/last_announcement.json']
errors = []
for f in files:
    path = os.path.join(os.getcwd(), f)
    if not os.path.exists(path):
        print(f'INFO: {f} does not exist yet (created on first use)')
        continue
    try:
        data = json.load(open(path))
        if f == 'data/followed_agents.json' and isinstance(data, dict):
            if 'following' in data:
                print(f'OK: {f} — {len(data[\"following\"])} following, {len(data.get(\"unfollowed\", []))} unfollowed')
            else:
                print(f'WARNING: {f} — dict format without \"following\" key')
        elif f == 'data/upvoted_post_ids.json':
            print(f'OK: {f} — {len(data)} posts upvoted')
        elif f == 'data/last_announcement.json' and isinstance(data, dict):
            print(f'OK: {f} — last_seen_id: {data.get(\"last_seen_id\", \"(legacy format)\")}')
        else:
            print(f'OK: {f} — {type(data).__name__}')
    except Exception as e:
        errors.append(f'PARSE ERROR: {f}: {e}')
if errors:
    for e in errors: print(e)
    sys.exit(1)
else:
    print('All engagement stores OK')
"
```

**Expected:** All files that exist are valid JSON with expected structure. Missing files (first use) are informational, not errors.

**If fails:** For `data/upvoted_post_ids.json`, delete or restore from backup (upvotes are idempotent). For `data/followed_agents.json`, delete or restore (follows are idempotent). For `data/last_announcement.json`, delete (re-created on next cycle — informational only).

### C8: Draft Deploy Note (Summary)

Before proceeding to restart, prepare the deploy note (see template below) with at minimum:
- Timestamp and commit hash
- Result of all pre-restart checks (pass/fail per item)
- Any deviations from the reference doc
- Link to relevant incident or change ticket

---

## Restart Steps (Post-Checklist)

### 1. Verify No Other Instance Is Running

```powershell
Get-Process -Name "python", "python3" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "run_agent|comet" }
```

If a process is found, do not restart until it is confirmed as dead or intentionally stopped.

### 2. Check State File Integrity

```powershell
# SQLite state - verify single-row, valid integers
python -c "
import sqlite3, sys
c = sqlite3.connect('data/comet_state.db')
row = list(c.execute('SELECT * FROM agent_state'))
c.close()
if not row:
    print('ERROR: agent_state table is empty')
    sys.exit(1)
print(f'Row: {row[0]}')
# Verify all integer fields are actually ints
for idx, name in enumerate(['id','cycle','posts_today','comments_today','consecutive_failures']):
    val = row[0][idx]
    if not isinstance(val, int):
        print(f'WARNING: {name}={val} is not int')
print('SQLite: OK')
"
```

Expected: a single row with `id=1`, all numeric fields are integers.

```powershell
# JSON state files - verify parseable AND valid content
Get-Content data/replied_comment_ids.json | python -c "
import json,sys
d = json.load(sys.stdin)
if not isinstance(d, list):
    print('ERROR: replied_comment_ids is not a list')
    sys.exit(1)
# Check all keys are valid format
invalid = [k for k in d if ':' not in str(k)]
if invalid:
    print(f'WARNING: {len(invalid)} entries without colon separator')
print(f'OK: {len(d)} entries')
"
Get-Content data/commented_post_ids.json | python -c "
import json,sys
d = json.load(sys.stdin)
if isinstance(d, list):
    print('WARNING: old list format, migration needed')
elif isinstance(d, dict):
    invalid = [k for k in d if not __import__('re').match(r'^[0-9a-f-]{36}$', str(k))]
    if invalid:
        print(f'WARNING: {len(invalid)} non-UUID keys')
print(f'OK: {len(d)} entries')
"
```

If any file fails to parse, inspect manually. Corrupted files should be restored from backup (`_archive/backups_*` or `*.stable-*` copies). **Never create state files from scratch unless you confirm the agent has zero published content today.**

### 3. Verify Daily Counters

```powershell
python -c "
import json
from pathlib import Path
# Count posts published today
today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
posts = json.loads(Path('data/own_post_ids.json').read_text()) if Path('data/own_post_ids.json').exists() else []
actual_posts = sum(1 for p in posts if p.get('published_at','').startswith(today))
# Count comments published today
comments = json.loads(Path('data/agent_comment_ids.json').read_text()) if Path('data/agent_comment_ids.json').exists() else {}
actual_comments = sum(1 for v in comments.values() if isinstance(v,dict) and v.get('timestamp','').startswith(today))
print(f'Posts today: {actual_posts}, Comments today: {actual_comments}')
"
```

Compare with `agent_state` values in SQLite. If SQLite counters are _lower_, the agent will attempt to publish again (risk of overposting on restart).

### 4. Verify Code Version vs Expected Version

```powershell
# Check current git commit
git log --oneline -5

# Verify the running version identifier matches the code
python -c "
from config.config import AgentVersion
from core.agent import COMETRiobambaAgent
print(f'Config version: {AgentVersion}')
print(f'Agent version: {COMETRiobambaAgent.__init__.__globals__[\"content_cfg\"].get(\"config_version\",\"?\")} if loaded')
"

# Check that CHANGELOG.md mentions this version
Select-String -Path CHANGELOG.md -Pattern "\[5.0.0\]" -SimpleMatch
```

If the repo is not at the expected commit (check `CHANGELOG.md` or operator log), deploy the correct version before restarting. **Known risk (INC-003): there is no CI/CD or automated version verification.**

### 4b. Version Consistency Check (Code vs State)

```powershell
# Verify the health.json version matches the code version
python -c "
import json
h = json.load(open('data/state/health.json'))
code_ver = '4.3.0'
state_ver = h.get('version', 'unknown')
if code_ver != state_ver:
    print(f'WARNING: Code version {code_ver} differs from state version {state_ver}')
else:
    print(f'Version consistent: {code_ver}')
"
```

### 5. Verify Environment Configuration

```powershell
# Check critical env vars are set
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
required = ['MOLTBOOK_API_KEY', 'MOLTBOOK_BASE_URL']
missing = [v for v in required if not os.getenv(v)]
if missing: print(f'MISSING: {missing}')
else: print('Required env vars: OK')
"
```

### 6. Verify LLM Provider Connectivity

```powershell
python -c "
from config.credentials import Credentials
c = Credentials.from_env()
# Test Gemini endpoint (or primary configured provider)
import httpx
r = httpx.get(c.moltbook_base_url, timeout=5)
print(f'Moltbook reachable: {r.status_code}')
"
```

### 7. Start the Agent

```powershell
python run_agent.py
```

Or use the deployment manager:

```powershell
.\deploy\comet_riobamba_manager.ps1 start
```

### 8. Minimal Dry-Run Before Full Restart

If the agent has NOT been running today (counters may be stale), run a cycle in whisper mode first:

```powershell
# Set whisper mode via env
$env:AGENT_WHISPER_MODE = "1"

# Run a single test cycle (if --once flag exists, otherwise Ctrl+C after first cycle)
python run_agent.py
# Observe output for first 60 seconds, then Ctrl+C

# If the cycle started cleanly, restart without whisper mode
Remove-Item Env:AGENT_WHISPER_MODE
```

### 9. Start the Agent

```powershell
python run_agent.py
```

Or use the deployment manager:

```powershell
.\deploy\comet_riobamba_manager.ps1 start
```

### 10. Verify Successful Start

```powershell
# Wait 60 seconds, then check
Start-Sleep -Seconds 60
Get-Content logs/agent.log -Tail 30
```

Expected: `COMET-RIOBAMBA v4.3.0` header, `config_summary` JSON block with version and limits, and `CICLO #N INICIADO`. Check for any ERROR-level messages in the first 30 lines.

Also verify health.json was written:

```powershell
Get-Content data/state/health.json | python -c "import json,sys; h=json.load(sys.stdin); print(f'Cycle {h[\"cycle\"]}, posts_today={h[\"posts_today\"]}')"
```

## Rollback

If the agent fails to start after verification:
1. Restore `.env` from backup (`.env.bak-*` or `.env.bak-limits`)
2. Restore SQLite from stable copy (`data/comet_state.db.stable-*`)
3. Try starting with `AGENT_WHISPER_MODE=1` to test without publishing

## Deploy Note Template

Copy this template into the incident/change ticket for every restart:

```
---
DEPLOY NOTE
-----------
Timestamp (UTC):      <YYYY-MM-DD HH:MM UTC>
Operator:             <name>
Commit hash:          <git rev-parse HEAD>
BUILD_IDENTITY match: Yes / No (explain)
Reason for restart:   <outage / planned maintenance / config change>

PRE-RESTART CHECKS
------------------
C1 (git clean):               PASS / FAIL — <notes>
C2 (commit match):            PASS / FAIL — <notes>
C3 (checksums match):         PASS / FAIL — <notes>
C4 (state files exist):       PASS / FAIL — <notes>
C5 (UUID stores clean):       PASS / FAIL — <notes>
C6 (evals pass):              <N/N passed, rate=N%>
C7 (health.json version):     PASS / FAIL — <notes>
C9 (engagement stores):       PASS / FAIL / N/A — <notes>

EVAL RESULT DETAILS
-------------------
Total cases:      31 (19 core + 12 engagement)
Passed:           <N>
Failed:           <N>
Pass rate:        <N>%
Threshold:        85%
Result:           PASS / FAIL

DEVIATIONS FROM REFERENCE DOC
-----------------------------
<list any discrepancies noted, or "None">

LINKS
-----
Incident ticket:  <link>
Change ticket:    <link>
Reference docs:   docs/COMET-RIOBAMBA_REFERENCE.md
BUILD identity:   docs/BUILD_IDENTITY.md
```

---
