import os, sys, requests
key = os.environ.get('_VALIDATE_KEY', '')
if not key:
    print('FAIL: key vacia'); sys.exit(1)
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
        print('FAIL: key rechazada por el servidor')
        sys.exit(2)
    else:
        print(f'FAIL: status inesperado {r.status_code}')
        print(r.text[:200])
        sys.exit(3)
except Exception as e:
    print(f'FAIL: {type(e).__name__}: {e}')
    sys.exit(4)
