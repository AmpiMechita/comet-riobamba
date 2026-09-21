# 🎯 ESTRATEGIA DE ENGAGEMENT - COMET-RIOBAMBA v31

**Fecha:** 2026-08-30  
**Objetivo:** Superar agentes top en Moltbook en 30 días

---

## 📊 DIAGNÓSTICO ACTUAL

| Agente | Karma | Comentarios/semana | Dual Score | Tu Posición |
|--------|-------|-------------------|------------|-------------|
| **vina** | 1.15M | 258 | 0.44 | 640x menos karma |
| **lobbyagent** | ? | 9 | **0.97** | Tu objetivo de calidad |
| **badbotnyc** | ? | 12 | **0.81** | Poco activo, alta calidad |
| **unknowntrialrandomizer** | ? | 27 | **0.75** | Alta calidad, volumen moderado |
| **comet_riobamba** | 1,808 | ~42 | ~0.65 | **En construcción** |

---

## 🎯 ESTRATEGIA DE SUPERACIÓN

### **Eje 1: Calidad + Timing (kombinación letal)**

**Objetivo:** Dual score > 0.85 + 20-30 comentarios/día

**Implementación:**
1. ✅ Priorizar threads de lobbyagent, badbotnyc, unknowntrialrandomizer
2. ✅ Comentar primero en sus posts (timing estratégico)
3. ✅ Aportar frameworks + empirical findings (mejores tipos de reply)

### **Eje 2: Optimización de Costos**

**Horas Valle DeepSeek (50% descuento):**
- **Fines de semana:** Todo el día (24h) ✅
- **Lunes-Viernes:** 17h valle (fuera de 01:00-04:00 UTC y 06:00-10:00 UTC) ✅

**Costos por operación (hora valle):**
- **Post:** $0.002904 (2k input + 800 output tokens)
- **Comentario:** $0.001584 (1.5k input + 300 output tokens)
- **Diario (20 comentarios):** $0.03168
- **Mensual:** ~$0.95

### **Eje 3: Watchlist Dinámica**

**Top Agents Prioritarios:**
1. **lobbyagent** (0.97 dual_score) → score_multiplier: 2.0
2. **badbotnyc** (0.81 dual_score) → score_multiplier: 1.8
3. **unknowntrialrandomizer** (0.75 dual_score) → score_multiplier: 1.7
4. **vina** (258 comentarios/semana) → score_multiplier: 1.5
5. **neo_konsi_s2bw** → score_multiplier: 1.5

---

## ⚙️ IMPLEMENTACIÓN TÉCNICA

### **Archivos Creados/Actualizados:**

1. ✅ `config/top_agents_watchlist.json` - Lista de top agents
2. ✅ `config/phase_b_strategy.yaml` - Actualizado con nuevos target_agents
3. ✅ `services/watchlist_manager.py` - Monitoreo de top agents
4. ✅ `services/thread_scorer.py` - Scoring de threads
5. ✅ `services/smart_rate_limiter.py` - Rate limiter inteligente
6. ✅ `services/engagement_orchestrator.py` - Orquestador de engagement

### **Integración con Fase B:**

Fase B ya tiene scoring robusto en:
- `phases/phase_b/candidate_scorer.py` - Scorea comentarios
- `phases/phase_b/scoring.py` - Relevancia y thresholds
- `phases/phase_b/orchestrator.py` - Coordina engagement

**Nuestra contribución:**
- Watchlist de top agents se integra con `_get_high_priority_agents()`
- Score multipliers se aplican automáticamente en el scoring existente
- Rate limiter optimiza costos (horas valle)

---

## 📈 MÉTRICAS OBJETIVO (30 días)

| Métrica | Actual | Objetivo | Estrategia |
|---------|--------|----------|------------|
| **Karma** | 1,808 | 5,000+ | Engagement en top agents |
| **Dual Score** | ~0.65 | >0.85 | Solo threads score >= 6 |
| **Comentarios/día** | 6 | 20-30 | Horas valle (50% descuento) |
| **Costo mensual** | ~$1.15 | ~$0.95 | Optimización horaria |
| **ROI** | 1x | 10x | Engagement estratégico |

---

## 🔧 COMANDOS CLAVE

### **Verificar estado del agente:**
```powershell
Get-Content data\agent_status.json
Get-Content data\performance_summary.json
```

### **Ver watchlist:**
```powershell
Get-Content config\top_agents_watchlist.json
```

### **Ver rate limits:**
```powershell
Get-Content data\rate_limit_state.json
```

### **Reiniciar agente:**
```powershell
Stop-Process -Id (Get-Process python | Where-Object {$_.Path -like "*comet-riobamba-v31*"}).Id
python run_agent.py
```

---

## 🚀 PRÓXIMOS PASOS

1. ✅ Watchlist configurada con top agents
2. ✅ Fase B actualizada con score multipliers
3. ⏳ Monitorear engagement en top agents (lobbyagent, badbotnyc, unknowntrialrandomizer)
4. ⏳ Ajustar umbrales según métricas reales
5. ⏳ Escalar a 20-30 comentarios/día en horas valle

---

## 📚 REFERENCIAS

- **Moltbook:** Red social para agentes IA (1.7M usuarios, 240k+ posts)
- **OpenClaw:** Bot que impulsa Moltbook (código abierto)
- **DeepSeek:** Modelo económico ($1.32/1M input, $3.96/1M output)
- **Horas Valle:** 50% descuento fuera de 01:00-04:00 UTC y 06:00-10:00 UTC

---

**Estado:** ✅ IMPLEMENTADO - Listo para operar en tiempo real
