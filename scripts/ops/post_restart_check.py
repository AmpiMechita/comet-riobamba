#!/usr/bin/env python
import json, os
from datetime import datetime, timezone
from collections import Counter

print("=== ESTADO DEL AGENTE DESPUÉS DEL REINICIO ===")
print()

# 1. Health check
if os.path.exists('data/state/health.json'):
    with open('data/state/health.json', 'r', encoding='utf-8') as f:
        health = json.load(f)
    print("1. health.json:")
    print(f"   cycle: {health.get('cycle')}")
    print(f"  posts_today: {health.get('posts_today')}")
    print(f"  phase_a posts_published: {health.get('phase_a', {}).get('posts_published')}")
    print(f"  phase_b replies_published: {health.get('phase_b', {}).get('replies_published')}")
    print(f"  last_error: {health.get('last_error')}")
    print(f"  updated_at: {health.get('updated_at')}")
else:
    print("1. health.json: NO EXISTE")

print()

# 2. Published posts hoy
with open('data/published_posts.json', 'r', encoding='utf-8') as f:
    posts = json.load(f)

today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
today_posts = [p for p in posts if p.get('published_at', '').startswith(today)]
print(f"\n2. Posts publicados hoy (UTC {today}): {len(today_posts)}")

# 3. Contar posts por fecha
date_counts = Counter()
for p in posts:
    pa = p.get('published_at', '')
    if pa:
        d = pa[:10]
        date_counts[d] += 1

print("\n3. Posts por fecha (últimos 5):")
for d, c in sorted(date_counts.items())[-5:]:
    print(f"  {d}: {c} posts")

# 4. Configuración .env
print("\n4. Configuración .env:")
print(f"  AGENT_PHASE_A_MODE: {os.getenv('AGENT_PHASE_A_MODE', 'no set')}")
print(f"  PHASE_A_NICHE_TOPICS: {os.getenv('PHASE_A_NICHE_TOPICS', 'no set')}")

# 5. agent_policy.py check
print("\n5. agent_policy.py max_posts_per_day:")
import re
with open('config/agent_policy.py', 'r', encoding='utf-8') as f:
    content = f.read()
m = re.search(r'max_posts_per_day:\s*(\S+)', content)
if m:
    print(f"  Valor: {m.group(1)}")

# 6. behavior_cfg.py check
print("\n6. behavior_cfg.py max_posts_per_day:")
with open('config/behavior_cfg.py', 'r', encoding='utf-8') as f:
    content = f.read()
if '"max_posts_per_day": None' in content:
    print("  ✅ max_posts_per_day = None")
else:
    m = re.search(r'"max_posts_per_day":\s*(\d+)', content)
    if m:
        print(f"  ❌ max_posts_per_day = {m.group(1)} (debería ser None)")

# 7. Orchestrator Phase B
print("\n7. phases/phase_b/orchestrator.py limits principales:")
with open('phases/phase_b/orchestrator.py', 'r', encoding='utf-8') as f:
    content = f.read()
lines = content.split('\n')
for i in range(53, 59):
    if i < len(lines):
        print(f"  Línea {i+1}: {lines[i][:100]}")

print("\n" + "=" * 50)
print("VERIFICACIÓN COMPLETADA")
PYEOF