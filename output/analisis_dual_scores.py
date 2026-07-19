"""Tarea 3: extraer evidencia real de dual_scores.jsonl — umbral EMPIRICAL."""
import json
import re
from collections import Counter
from pathlib import Path

PATH = Path("data/dual_scores.jsonl")
records = []

with PATH.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

print(f"Archivo: {PATH.resolve()}")
print(f"Registros totales: {len(records)}")
print()

# Distribución por tipo
types = Counter(r["type"] for r in records)
print("=== Distribución por tipo de contenido ===")
for t, count in sorted(types.items(), key=lambda x: -x[1]):
    print(f"  {t:30s} {count:4d} ({100*count/len(records):5.1f}%)")

# Identificar empirical_finding
empirical = [r for r in records if r["type"] == "empirical_finding"]
print(f"\n=== Empirical finding con umbral actual (≥1 señal) ===")
print(f"  Cantidad: {len(empirical)} ({100*len(empirical)/len(records):.1f}% del total)")
if empirical:
    composites = [e["composite"] for e in empirical]
    print(f"  Composite score: min={min(composites):.4f}  max={max(composites):.4f}  media={sum(composites)/len(composites):.4f}")

# Simular umbral 2: re-clasificar textos empirical_finding con ≥2 señales
SIGNALS = [
    "measured", "observed", "in our tests", "in production", "data shows",
    "latency", "throughput", "we deployed", "we benchmarked",
]

def count_signals(text):
    t = text.lower()
    return sum(1 for p in SIGNALS if p in t)

empirical_umbral2 = []
for r in empirical:
    text_preview = r.get("text_preview", "")
    if count_signals(text_preview) >= 2:
        empirical_umbral2.append(r)

print(f"\n=== Simulación: empirical_finding con umbral 2 (≥2 señales) ===")
print(f"  Cantidad: {len(empirical_umbral2)} ({100*len(empirical_umbral2)/len(empirical):.1f}% de los empirical actuales)")
print(f"  Diferencia absoluta: {len(empirical) - len(empirical_umbral2)} registros menos")
print(f"  Diferencia porcentual: {100*(len(empirical)-len(empirical_umbral2))/len(empirical):.1f}% de reducción")

# Qué tipos tendrían esos registros bajo umbral 2 (ejecutar classify_content offline)
# Solo miramos text_preview, no el texto completo — aproximación
print(f"\n=== Sample textos que PERDERÍAN la clasificación empirical con umbral 2 ===")
diferencia = [r for r in empirical if r not in empirical_umbral2]
for d in diferencia[:8]:
    print(f"  [{d['phase']}] comp={d['composite']:.3f}  {d['text_preview'][:90]}")

print(f"\n=== Resumen ===")
print(f"  Umbral actual (≥1): {len(empirical)} empirical_finding")
print(f"  Umbral 2 (≥2):     {len(empirical_umbral2)} empirical_finding")
print(f"  Diferencia:         {len(empirical) - len(empirical_umbral2)} registros ({100*(len(empirical)-len(empirical_umbral2))/max(len(empirical),1):.1f}%)")
