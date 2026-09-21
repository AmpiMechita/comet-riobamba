"""Reparador de mojibake con dry-run por defecto.

Uso:
    python scripts/fix_mojibake.py <archivo>              # dry-run, muestra diff
    python scripts/fix_mojibake.py <archivo> --apply      # aplica cambios

Siempre verifica que el resultado sea UTF-8 valido antes de escribir.
"""
from __future__ import annotations

import sys
from pathlib import Path


# Tabla de reemplazos. IMPORTANTE: orden importa.
# Las secuencias mas largas van primero para evitar matches parciales.
# Ej: "âÂ§" debe reemplazarse ANTES que "Â§", o quedaría "â-" sin limpiar.
REPLACEMENTS = [
    ("âÂ§", "-"),        # sub-bullets: dash ASCII (robusto)
    ("â§ª", "\U0001f527"),  # 🔧 header (emoji restaurado)
    ("Â§", "-"),          # fallback por si queda algun fragmento suelto
]


def load_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def compute_new_lines(lines: list[str]) -> tuple[list[str], int]:
    """Devuelve (lineas_nuevas, total_reemplazos)."""
    new_lines: list[str] = []
    total = 0
    for line in lines:
        new_line = line
        for old, new in REPLACEMENTS:
            if old in new_line:
                count = new_line.count(old)
                new_line = new_line.replace(old, new)
                total += count
        new_lines.append(new_line)
    return new_lines, total


def show_diff(old_lines: list[str], new_lines: list[str], path: Path) -> None:
    print(f"\n=== DIFF en {path} ===")
    for i, (old, new) in enumerate(zip(old_lines, new_lines), start=1):
        if old != new:
            print(f"\nL{i}:")
            print(f"  - {old.rstrip()}")
            print(f"  + {new.rstrip()}")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    apply_changes = "--apply" in argv

    if not args:
        print("Uso: python scripts/fix_mojibake.py <archivo> [--apply]")
        return 1

    exit_code = 0
    for arg in args:
        path = Path(arg)
        if not path.exists():
            print(f"!! {path}: no existe")
            exit_code = 1
            continue

        try:
            old_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            print(f"!! {path}: NO es UTF-8 valido ({e})")
            exit_code = 1
            continue

        old_lines = old_text.splitlines(keepends=True)
        new_lines, total = compute_new_lines(old_lines)

        if total == 0:
            print(f"OK {path}: sin mojibake conocido (0 cambios)")
            continue

        show_diff(old_lines, new_lines, path)
        print(f"\n  Total: {total} reemplazo(s) en {path}")

        if not apply_changes:
            print(f"  [DRY-RUN] No se escribio nada. Usar --apply para aplicar.")
            continue

        new_text = "".join(new_lines)
        new_text.encode("utf-8")  # lanza si hay problema de encoding
        path.write_text(new_text, encoding="utf-8")
        print(f"  [APLICADO] {path} actualizado")

    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))