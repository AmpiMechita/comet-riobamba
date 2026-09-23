#!/usr/bin/env python3
r"""Rotacion segura de MOLTBOOK_API_KEY con backup + rollback (P-049).

Uso:
  1. Escribir la nueva key en data\.secrets_backup\new_key.tmp
  2. .\tools\nssm.exe stop CometRiobamba
  3. python scripts\rotate_key.py [--dry-run]
  4. .\tools\nssm.exe start CometRiobamba
"""
from __future__ import annotations
import argparse, shutil, sys
from datetime import datetime
from pathlib import Path

NEW_KEY_PATH    = Path("data/.secrets_backup/new_key.tmp")
BACKUP_DIR      = Path("data/.secrets_backup")
DPAPI_BLOB      = Path("data/.secrets/moltbook_api_key.enc")
KEYRING_SERVICE = "comet_riobamba"
KEYRING_USER    = "moltbook_api_key"
FEED_URL        = "https://www.moltbook.com/api/v1/feed"


def validate_key(key: str):
    """Devuelve (ok, mensaje). No persiste nada."""
    import requests
    try:
        r = requests.get(
            FEED_URL,
            headers={"Authorization": f"Bearer {key}"},
            params={"limit": 1},
            timeout=10,
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if r.status_code == 200:
        return True, "OK"
    if r.status_code in (401, 403):
        return False, "key rechazada"
    return False, f"status inesperado {r.status_code}"


def read_new_key() -> str:
    if not NEW_KEY_PATH.exists():
        print(f"FAIL: no existe {NEW_KEY_PATH}"); sys.exit(1)
    key = NEW_KEY_PATH.read_bytes().decode("utf-8").strip()
    if not key:
        print("FAIL: key vacia"); sys.exit(2)
    return key


def backup_current() -> Path:
    if not DPAPI_BLOB.exists():
        print(f"FAIL: no existe {DPAPI_BLOB}"); sys.exit(3)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"moltbook_api_key.{ts}.enc"
    shutil.copy2(DPAPI_BLOB, dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Solo valida; no escribe, no borra temp")
    args = ap.parse_args()

    print("[1/5] Leyendo nueva key")
    new_key = read_new_key()
    print(f"      len={len(new_key)}")

    print("[2/5] Validando contra Moltbook")
    ok, msg = validate_key(new_key)
    if not ok:
        print(f"FAIL validacion: {msg}")
        sys.exit(4)
    print(f"      OK ({msg})")

    if args.dry_run:
        print("DRY-RUN: validacion OK, no se escribio nada")
        return

    print("[3/5] Backup del blob DPAPI")
    backup_path = backup_current()
    print(f"      {backup_path}")

    import keyring
    old_keyring = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    print(f"      keyring actual: {'presente' if old_keyring else 'ausente'}")

    print("[4/5] Escribiendo nueva key (DPAPI + keyring)")
    from services.secret_store import set_secret, get_secret
    try:
        set_secret("moltbook_api_key", new_key)
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, new_key)
        k_dpapi   = get_secret("moltbook_api_key") or ""
        k_keyring = keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
        if k_dpapi != new_key or k_keyring != new_key:
            raise RuntimeError(
                "post-escritura no coincide: "
                f"dpapi_len={len(k_dpapi)} keyring_len={len(k_keyring)}"
            )
        print("      verificacion post-escritura OK")
    except Exception as e:
        print(f"FAIL escribiendo: {e}")
        print("      ROLLBACK en curso...")
        try:
            shutil.copy2(backup_path, DPAPI_BLOB)
            if old_keyring is None:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            else:
                keyring.set_password(KEYRING_SERVICE, KEYRING_USER, old_keyring)
            print("      rollback OK")
        except Exception as e2:
            print(f"      ROLLBACK FALLO: {e2}")
            print(f"      restaurar manualmente desde: {backup_path}")
            sys.exit(7)
        sys.exit(6)

    print("[5/5] Borrando temp")
    NEW_KEY_PATH.unlink()
    print("OK: rotacion completa")
    print(f"Backup guardado en: {backup_path}")


if __name__ == "__main__":
    main()
