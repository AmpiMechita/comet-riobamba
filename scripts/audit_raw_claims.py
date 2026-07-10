#!/usr/bin/env python3
"""
Auditoría de verdad fundacional — Energy Intel Node.

Volcado legible de energy_intel.db + verificación de hallazgos del informe LLM.
"""

import sqlite3
import sys
from pathlib import Path

_proj_root = Path(__file__).resolve().parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

DB_PATH = _proj_root / "energy_intel.db"


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA read_uncommitted = 1")

    cur = conn.execute("SELECT COUNT(*) FROM claims")
    total = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM claims WHERE technology = 'other'")
    other_count = cur.fetchone()[0]

    rows = conn.execute(
        "SELECT * FROM claims WHERE technology != 'other' ORDER BY date_pub DESC"
    ).fetchall()

    print("=" * 66)
    print("   AUDITORIA DE VERDAD FUNDACIONAL — EIN".center(66))
    print("=" * 66)
    print(f"Total de claims en DB: {total}")
    print(f"Claims excluidos (tecnologia 'other'): {other_count}")
    print(f"Claims analizados: {len(rows)}")
    print()

    for i, r in enumerate(rows, 1):
        print(f"--- CLAIM #{i} ---")
        print(f"ID: {r['id']}")
        print(f"Fuente: {r['source_type']} — {r['source_url']}")
        print(f"Tecnologia: {r['technology']}")
        print(f"Texto del Claim: {r['claim_text'][:600]}")
        mv = r['metric_value']
        mu = r['metric_unit'] or ""
        print(f"Metrica Extraida: {mv} {mu}".strip())
        print(f"Estado de Validacion: {r['status']}")
        print(f"Fecha Publicacion: {r['date_pub']}")
        print()

    # ── VERIFICACION DE HALLAZGOS ──────────────────────────────────────────

    print("=" * 66)
    print("   VERIFICACION DE HALLAZGOS DEL INFORME LLM".center(66))
    print("=" * 66)
    print()

    # Hallazgo 1: Boston Metal / green-hydrogen
    print("[1] Boston Metal — presunto pivot de acero verde a metales criticos")
    print("-" * 40)
    boston_rows = conn.execute(
        "SELECT * FROM claims WHERE technology = 'green-hydrogen' "
        "AND (claim_text LIKE '%Boston%' OR claim_text LIKE '%metal%' OR claim_text LIKE '%Metal%')"
    ).fetchall()
    if boston_rows:
        for r in boston_rows:
            print(f"  ID: {r['id']}")
            print(f"  Fuente: {r['source_url']}")
            print(f"  Texto: {r['claim_text'][:500]}")
            print()
    else:
        rows_gh = conn.execute(
            "SELECT * FROM claims WHERE technology = 'green-hydrogen'"
        ).fetchall()
        if rows_gh:
            print("  *** NO SE ENCONTRO 'Boston' ni 'metal' en green-hydrogen.")
            print(f"  Total claims green-hydrogen en DB: {len(rows_gh)}")
            for r in rows_gh:
                print(f"  ID: {r['id']} | URL: {r['source_url']}")
                print(f"  Texto: {r['claim_text'][:300]}")
                print()
        else:
            print("  *** NO HAY claims de tecnologia 'green-hydrogen' en DB.")
    print()

    # Hallazgo 2: Perovskita 33.7%
    print("[2] Perovskitas — eficiencia del 33.7% marcado como 'disputed'")
    print("-" * 40)
    pv_rows = conn.execute(
        "SELECT * FROM claims WHERE claim_text LIKE '%33.7%' OR claim_text LIKE '%33,7%' "
        "OR claim_text LIKE '%perovskite%' OR claim_text LIKE '%perovskita%'"
    ).fetchall()
    if pv_rows:
        for r in pv_rows:
            print(f"  ID: {r['id']}")
            print(f"  Tecnologia: {r['technology']}")
            print(f"  Status: {r['status']}")
            print(f"  Texto: {r['claim_text'][:500]}")
            print()
    else:
        print("  *** NO SE ENCONTRO ningun claim que mencione perovskita o '33.7'.")
        print("  *** La DB NO contiene tecnologia 'perovskite'.")
        all_techs = [r[0] for r in conn.execute("SELECT DISTINCT technology FROM claims").fetchall()]
        print(f"  Tecnologias disponibles: {all_techs}")
    print()

    # Hallazgo 3: AgriPV — datos de rendimiento agricola
    print("[3] AgriPV — ausencia de datos de rendimiento agricola (crop/yield)")
    print("-" * 40)
    agri_rows = conn.execute(
        "SELECT * FROM claims WHERE technology = 'agrivoltaics' "
        "AND (claim_text LIKE '%crop%' OR claim_text LIKE '%yield%' OR claim_text LIKE '%rendimiento%')"
    ).fetchall()
    agri_all = conn.execute(
        "SELECT * FROM claims WHERE technology = 'agrivoltaics'"
    ).fetchall()
    print(f"  Total claims agrivoltaics en DB: {len(agri_all)}")
    if agri_rows:
        for r in agri_rows:
            print(f"  ID: {r['id']}")
            print(f"  Texto: {r['claim_text'][:500]}")
            print()
    else:
        print("  *** NO SE ENCONTRO 'crop', 'yield' ni 'rendimiento' en claims agrivoltaics.")
        print("  *** La afirmacion del LLM es CORRECTA: no hay datos de rendimiento agricola.")
        print()
        for r in agri_all:
            print(f"  ID: {r['id']}")
            print(f"  Fuente: {r['source_url']}")
            print(f"  Texto: {r['claim_text'][:400]}")
            print()

    conn.close()


if __name__ == "__main__":
    main()
