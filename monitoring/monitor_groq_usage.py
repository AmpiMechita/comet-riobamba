#!/usr/bin/env python3
"""
Monitor de uso de Groq y fallback para comet-riobamba-v31
Analiza logs y muestra estadísticas de uso por proveedor
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

# Detectar directorio del proyecto
SCRIPT_DIR = Path(__file__).parent
LOGS_DIR = SCRIPT_DIR.parent / "logs"
AGENT_LOG = LOGS_DIR / "agent.log"

print("=" * 80)
print("MONITOR DE USO DE GROQ Y FALLBACK")
print("=" * 80)
print(f"Log file: {AGENT_LOG}")

if not AGENT_LOG.exists():
    print(f"❌ Log file no encontrado: {AGENT_LOG}")
    exit(1)

# Leer log
print("\nLeyendo logs...")
with open(AGENT_LOG, "r", encoding="utf-8") as f:
    log_lines = f.readlines()

print(f"✅ {len(log_lines)} líneas leídas")

# Patrones a buscar (formato real de model_cascade)
patterns = {
    "groq_success": "✅ ModelCascade: éxito con 'groq'",
    "groq_attempt": "ModelCascade: intentando 'groq'",
    "groq_fail": "fallo en 'groq'",
    "openrouter_success": "✅ ModelCascade: éxito con 'openrouter'",
    "openrouter_attempt": "ModelCascade: intentando 'openrouter'",
    "openrouter_fail": "fallo en 'openrouter'",
    "deepseek_success": "✅ ModelCascade: éxito con 'tier_fallback'",
    "deepseek_attempt": "ModelCascade: intentando 'tier_fallback'",
    "deepseek_fail": "fallo en 'tier_fallback'",
    "rate_limit": "429",
    "timeout": "Timeout",
    "fallback": "cayendo a fallback",
}

# Contar ocurrencias
counts = Counter()
groq_times = []
openrouter_times = []
deepseek_times = []

for line in log_lines:
    line_lower = line.lower()
    
    for key, pattern in patterns.items():
        if pattern.lower() in line_lower:
            counts[key] += 1
    
    # Extraer tiempos de respuesta
if "ModelCascade: éxito con 'groq'" in line:
    try:
        # Buscar patrón: "en X.XXs" o similar
        import re
        match = re.search(r'en (\d+\.\d+)s', line)
        if match:
            groq_times.append(float(match.group(1)))
    except:
        pass

if "ModelCascade: éxito con 'openrouter'" in line:
    try:
        import re
        match = re.search(r'en (\d+\.\d+)s', line)
        if match:
            openrouter_times.append(float(match.group(1)))
    except:
        pass

if "ModelCascade: éxito con 'tier_fallback'" in line or "AUDIT DEEPSEEK" in line:
    try:
        import re
        match = re.search(r'en (\d+\.\d+)s', line)
        if match:
            deepseek_times.append(float(match.group(1)))
    except:
        pass
    
    if "openrouter respondió en" in line:
        try:
            time_str = line.split("en ")[1].split("s")[0]
            openrouter_times.append(float(time_str))
        except:
            pass
    
    if "deepseek respondió en" in line:
        try:
            time_str = line.split("en ")[1].split("s")[0]
            deepseek_times.append(float(time_str))
        except:
            pass

# Calcular estadísticas
def calc_stats(times, name):
    if not times:
        return f"{name}: N/A"
    avg = sum(times) / len(times)
    min_t = min(times)
    max_t = max(times)
    return f"{name}: avg={avg:.2f}s, min={min_t:.2f}s, max={max_t:.2f}s ({len(times)} requests)"

# Mostrar resultados
print("\n" + "=" * 80)
print("ESTADISTICAS DE USO")
print("=" * 80)

print(f"\n📊 Intentos por proveedor:")
print(f"  Groq:        {counts['groq_attempt']} intentos")
print(f"  OpenRouter:  {counts['openrouter_attempt']} intentos")
print(f"  DeepSeek:    {counts['deepseek_attempt']} intentos")

print(f"\n✅ Éxitos por proveedor:")
print(f"  Groq:        {counts['groq_success']} éxitos")
print(f"  OpenRouter:  {counts['openrouter_success']} éxitos")
print(f"  DeepSeek:    {counts['deepseek_success']} éxitos")

print(f"\n⚠️  Errores:")
print(f"  Rate limits: {counts['rate_limit']}")
print(f"  Timeouts:    {counts['timeout']}")
print(f"  Fallbacks:   {counts['fallback']}")

print(f"\n⏱️  Tiempos de respuesta:")
print(f"  {calc_stats(groq_times, 'Groq')}")
print(f"  {calc_stats(openrouter_times, 'OpenRouter')}")
print(f"  {calc_stats(deepseek_times, 'DeepSeek')}")

# Calcular tasa de fallback
total_attempts = counts['groq_attempt'] + counts['openrouter_attempt'] + counts['deepseek_attempt']
total_fallbacks = counts['fallback']
fallback_rate = (total_fallbacks / total_attempts * 100) if total_attempts > 0 else 0

print(f"\n📈 Métricas de fallback:")
print(f"  Total requests: {total_attempts}")
print(f"  Fallbacks: {total_fallbacks} ({fallback_rate:.1f}%)")
print(f"  Tasa de éxito Groq: {counts['groq_success'] / counts['groq_attempt'] * 100 if counts['groq_attempt'] > 0 else 0:.1f}%")

# Límites de Groq
print(f"\n🎯 Límites de Groq free tier:")
print(f"  RPM límite: 30 (actual: {counts['groq_success']} requests/hora)")
print(f"  RPD límite: 14,400 (actual: {counts['groq_success']} requests/día)")
print(f"  Estado: {'✅ OK' if counts['groq_success'] < 14400 else '⚠️  Cerca del límite'}")

print("\n" + "=" * 80)
print("FIN DEL REPORTE")
print("=" * 80)