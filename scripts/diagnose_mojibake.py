"""Diagnostico de mojibake en archivos de codigo.

Uso:
    python scripts/diagnose_mojibake.py [archivos...]
    (sin argumentos: escanea el repo completo)
"""
import sys
from pathlib import Path

# Secuencias tipicas de mojibake (UTF-8 mal decodificado como Latin-1)
# Cada tupla: (secuencia_corrupta, caracter_correcto_probable)
MOJIBAKE = [
    ("\u00c3\u00a1", "á"), ("\u00c3\u00a9", "é"), ("\u00c3\u00ad", "í"),
    ("\u00c3\u00b3", "ó"), ("\u00c3\u00ba", "ú"), ("\u00c3\u00b1", "ñ"),
    ("\u00c2\u00a1", "¡"), ("\u00c2\u00bf", "¿"),
    ("\u00c2\u00a7", "§"), ("\u00c2\u00b7", "·"),
    ("\u00e2\u0080\u0094", "—"), ("\u00e2\u0080\u0093", "–"),
    ("\u00e2\u0080\u009c", "“"), ("\u00e2\u0080\u009d", "”"),
    ("\u00e2\u00a7\u00aa", "🔧"), ("\u00f0\u009f", "🧪"),
]


def scan(path: Path) -> list[tuple[int, str, str, str]]:
    """Devuelve [(line_no, moji, replacement, contexto), ...]."""
    hits = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(f"  !! {path}: NO es UTF-8 valido ({e})")
        return hits

    for line_no, line in enumerate(text.splitlines(), start=1):
        for moji, repl in MOJIBAKE:
            if moji in line:
                hits.append((line_no, moji, repl, line.strip()[:90]))
    return hits


def main(targets: list[str]) -> int:
    if not targets:
        targets = [str(p) for p in Path(".").rglob("*.py") if ".venv" not in str(p) and "site-packages" not in str(p)]

    total = 0
    for target in targets:
        p = Path(target)
        if not p.exists():
            continue
        hits = scan(p)
        if hits:
            print(f"\n=== {p} ({len(hits)} hits) ===")
            for line_no, moji, repl, ctx in hits:
                print(f"  L{line_no}: {moji!r} -> {repl!r}")
                print(f"         {ctx}")
            total += len(hits)
    print(f"\nTOTAL: {total} secuencias de mojibake en {len(targets)} archivos")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))