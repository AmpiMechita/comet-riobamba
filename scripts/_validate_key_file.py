import sys, os, requests
path = 'new_key.tmp'
if not os.path.exists(path):
    print(f'FAIL: no existe {path}'); sys.exit(1)
with open(path, 'r', encoding='utf-8') as f:
    key = f.read().strip()
os.remove(path)
if not key:
    print('FAIL: key vacia'); sys.exit(2)
try:
    r = requests.get(
        'https://www.moltbook.com/api/v1/feed',
        headers={'Authorization': f'Bearer {key}'},
        params={'limit': 1},
        timeout=10,
    )
    print(f'HTTP {r.status_code}')
    if r.status_code == 200:
        print('OK: key valida')
        sys.exit(0)
    elif r.status_code in (401, 403):
        print('FAIL: key rechazada')
        sys.exit(3)
    else:
        print(f'FAIL: status {r.status_code}: {r.text[:200]}')
        sys.exit(4)
except Exception as e:
    print(f'FAIL: {type(e).__name__}: {e}')
    sys.exit(5)
