"""Machine-scoped encrypted secret store using Windows DPAPI.

Only processes on this machine can decrypt. Suitable for services running
under LocalSystem account (e.g. NSSM-managed processes).

Migrated 2026-09-21: MOLTBOOK_API_KEY from .env plaintext -> encrypted blob.
Threat model: platform breach (e.g. Moltbook feb-2026 leak), accidental
exposure via logs or backup copies. Physical access to the machine is
out of scope for this layer.
"""
from __future__ import annotations

from pathlib import Path

# CRYPTPROTECT_LOCAL_MACHINE = 0x04
# No expuesta por win32crypt en pywin32 312; valor oficial del SDK de Windows.
# https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
CRYPTPROTECT_LOCAL_MACHINE = 0x04


SECRETS_DIR = Path("data/.secrets")
_GITIGNORE = SECRETS_DIR / ".gitignore"


def _ensure_dir() -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    if not _GITIGNORE.exists():
        _GITIGNORE.write_text("*\n!.gitignore\n", encoding="utf-8")


def _path_for(name: str) -> Path:
    return SECRETS_DIR / f"{name}.enc"


def set_secret(name: str, value: str) -> None:
    """Encrypt and persist a secret for this machine."""
    import win32crypt
    _ensure_dir()
    blob = win32crypt.CryptProtectData(
        value.encode("utf-8"),
        None, None, None, None,
        CRYPTPROTECT_LOCAL_MACHINE,
    )
    if isinstance(blob, tuple):
        blob = blob[1]
    _path_for(name).write_bytes(blob)


def get_secret(name: str, default: str = "") -> str:
    """Read and decrypt a secret. Returns default if missing or unreadable."""
    p = _path_for(name)
    if not p.exists():
        return default
    try:
        import win32crypt
        blob = p.read_bytes()
        # Firma: (blob, description, entropy, reserved, prompt)
        # prompt debe ser int (0 = sin UI). None revienta en pywin32 312.
        result = win32crypt.CryptUnprotectData(
            blob, None, None, None, 0,
        )
        data = result[1] if isinstance(result, tuple) else result
        return data.decode("utf-8")
    except Exception:
        return default


def delete_secret(name: str) -> bool:
    p = _path_for(name)
    if p.exists():
        p.unlink()
        return True
    return False
