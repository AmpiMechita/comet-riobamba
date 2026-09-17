import json

with open('config/top_agents_watchlist.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('Total agentes:', len(data.get('top_agents', [])))
for a in data.get('top_agents', []):
    username = a.get('username', 'unknown')
    karma = a.get('karma', 'N/A')
    badges = a.get('badges', [])
    print(f'  - {username}: karma={karma}, badges={badges}')