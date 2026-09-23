import sys, os
sys.path.insert(0, '.')
import requests

path = 'new_key.tmp'
if not os.path.exists(path):
    print('FAIL: no existe', path); sys.exit(1)
with open(path, 'r', encoding='utf-8') as f:
    key = f.read().strip()
if not key:
    print('FAIL: key vacia'); sys.exit(2)

# 1) Validar
try:
    r = requests.get(
        'https://www.moltbook.com/api/v1/feed',
        headers={'Authorization': 'Bearer ' + key},
        params={'limit': 1},
        timeout=10,
    )
    if r.status_code != 200:
        print('FAIL validacion: HTTP', r.status_code)
        sys.exit(3)
except Exception as e:
    print('FAIL validacion:', type(e).__name__, str(e))
    sys.exit(4)
print('Validacion OK')

# 2) Guardar en DPAPI
from services.secret_store import set_secret, get_secret
set_secret('moltbook_api_key', key)
print('DPAPI guardado')

# 3) Guardar en keyring
import keyring
keyring.set_password('comet_riobamba', 'moltbook_api_key', key)
print('Keyring guardado')

# 4) Verificar lectura desde ambos
k_dpapi = get_secret('moltbook_api_key') or ''
k_keyring = keyring.get_password('comet_riobamba', 'moltbook_api_key') or ''
if k_dpapi != key or k_keyring != key:
    print('FAIL: verificacion post-escritura no coincide')
    print('  dpapi_len=%d keyring_len=%d' % (len(k_dpapi), len(k_keyring)))
    sys.exit(5)
print('Verificacion post-escritura OK')

# 5) Borrar archivo temporal
os.remove(path)
print('Archivo temporal borrado')
print('OK: rotacion completa')
sys.exit(0)
