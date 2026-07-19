"""Tarea 3b: analisis offline de dual_scores.jsonl usando classify_content() real.

Limitacion conocida: dual_scores.jsonl solo almacena text_preview ([:100]),
no el texto completo. La re-clasificacion sobre preview es una aproximacion
que subestima las senales presentes en el texto original.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Usar la funcion real de clasificacion
from services.dual_scoring import classify_content, ResearchValueType

PATH = Path("data/dual_scores.jsonl")
records = []

with PATH.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

N = len(records)
print(f"Archivo: {PATH.resolve()}")
print(f"Registros totales: {N}")
print()

# ── 1. Distribucion real (clasificacion original sobre texto completo) ──
print("=" * 50)
print("1. DISTRIBUCION ORIGINAL (classify_content sobre texto completo)")
print("=" * 50)
orig_types = Counter(r["type"] for r in records)
for t, count in sorted(orig_types.items(), key=lambda x: -x[1]):
    print(f"  {t:30s} {count:4d} ({100*count/N:5.1f}%)")

# ── 2. Re-clasificacion sobre text_preview (100 chars) ──
print()
print("=" * 50)
print("2. RECLASIFICACION SOBRE TEXT_PREVIEW (100 chars)")
print("=" * 50)
reclass_types = Counter()
reclass_details = []
for r in records:
    prev = r.get("text_preview", "")
    actual_type = classify_content(prev)
    reclass_types[actual_type.value] += 1
    if actual_type.value != r["type"]:
        reclass_details.append((r["type"], actual_type.value, prev))

for t, count in sorted(reclass_types.items(), key=lambda x: -x[1]):
    print(f"  {t:30s} {count:4d} ({100*count/N:5.1f}%)")

# ── 3. Discrepancias por truncamiento ──
print()
print("=" * 50)
print("3. DISCREPANCIAS POR TRUNCAMIENTO (preview != full text)")
print("=" * 50)
print(f"  Registros que cambiarian de tipo con solo 100 chars: {len(reclass_details)}")
if reclass_details:
    changes = Counter(f"{a} -> {b}" for a, b, _ in reclass_details)
    for change, count in sorted(changes.items(), key=lambda x: -x[1]):
        print(f"    {change:40s} {count:4d}")
    print()
    print("  Muestras de discrepancias:")
    for a, b, t in reclass_details[:8]:
        print(f"    Original={a:25s} Preview-classify={b:25s} | {t[:70]}")

# ── 4. Empirical: simulacion umbral 1 vs umbral 2 (sobre preview) ──
print()
print("=" * 50)
print("4. SIMULACION UMBRAL EMPIRICAL (≥1 vs ≥2 senales)")
print("=" * 50)

SIGNALS = [
    "measured", "observed", "in our tests", "in production", "data shows",
    "latency", "throughput", "we deployed", "we benchmarked",
]

def count_signals(text):
    t = text.lower()
    return sum(1 for p in SIGNALS if p in t)

empirical = [r for r in records if r["type"] == "empirical_finding"]
umbral1 = len(empirical)
umbral2 = sum(1 for r in empirical if count_signals(r.get("text_preview", "")) >= 2)

print(f"  Umbral ≥1 (actual): {umbral1:4d} ({100*umbral1/N:.1f}% del total)")
print(f"  Umbral ≥2:          {umbral2:4d} ({100*umbral2/N:.1f}% del total)")
print(f"  Diferencia:         {umbral1 - umbral2:4d} registros menos ({100*(umbral1-umbral2)/max(umbral1,1):.1f}% de reduccion)")

# Texots que perderian clasificacion
perdidos = [r for r in empirical if count_signals(r.get("text_preview", "")) < 2]
print(f"\n  Texots que PIERDEN clasificacion empirical con umbral ≥2 ({len(perdidos)} muestras):")
for p in perdidos[:6]:
    signals_found = [s for s in SIGNALS if s in p.get("text_preview", "").lower()]
    print(f"    senales={signals_found}  {p['text_preview'][:80]}")
if len(perdidos) > 6:
    print(f"    ... y {len(perdidos) - 6} mas")

# ── 5. Resumen ejecutivo ──
print()
print("=" * 50)
print("5. RESUMEN")
print("=" * 50)
print(f"  Registros totales:               {N}")
print(f"  Tipos en datos:                  {', '.join(sorted(orig_types.keys()))}")
print(f"  Tipos NO encontrados:            {', '.join(t.value for t in ResearchValueType if t.value not in orig_types)}")
print(f"  Empirical (umbral actual):       {umbral1}")
print(f"  Empirical (umbral ≥2 simulado):  {umbral2}")
print(f"  Reduccion simulada:              {umbral1 - umbral2} ({100*(umbral1-umbral2)/max(umbral1,1):.1f}%)")
print(f"  Discrepancias truncamiento:      {len(reclass_details)} registros")
print(f"  Composite tipico empirical:      0.665 (engagement=0, solo peso textual)")
print(f"  Limitacion:                      text_preview=100 chars, sin texto completo")
