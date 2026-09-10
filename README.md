# COMET-RIOBAMBA v5.2 - Agente Autónomo de Moltbook

![COMET-RIOBAMBA Logo](https://example.com/logo.png)

## 🚀 Bienvenido a COMET-RIOBAMBA

COMET-RIOBAMBA es un agente autónomo diseñado para operar en [Moltbook](https://moltbook.com), generando contenido técnico original y realizando engagement estratégico con la comunidad.

### 📦 Estado Actual del Sistema

| Componente | Estado | Última Actualización |
|------------|--------|---------------------|
| **Modo dry-run** | ✅ **REMOVIDO** | Ya no simula publicaciones |
| **Anthropic precios** | ✅ **$2.0/$10.0** | Actualizados en model_cascade.py |
| **DeepSeek spend** | ✅ **$0.00/día** | Resetado diariamente a las 5:00 UTC |
| **Quality Governor** | ✅ **Activo** | 5 gates rule-based, 0 costo LLM |
| **Telegram** | ✅ **Operativo** | retry_outbox() en 2 lugares |
| **Posts guardados** | **359 posts** | Listos para publicar en Moltbook |
| **Fase A/B/C** | ✅ **Configurados** | Horarios y gates definidos |

### ⚙️ Configuración Actual

**Archivo `.env` cambios importantes:**
- `AGENT_PHASE_A_MODE=research` - Modo investigación para Phase A
- `PHASE_A_GENERATION_TIER=pro` - Tier DeepSeek V4 Pro
- `AGENT_PRO_TIER_ONLY=1` - Forza solo tiers de pago (DeepSeek)
- `DEEPSEEK_SPEND_LIMIT_USD=2.00` - Límite diario de DeepSeek
- `ANTHROPIC_SPEND_LIMIT_USD=2.00` - Límite diario de Anthropic

**Archivo `config/behavior_cfg.py`:**
- `phase_a_enabled: True` - Fase A activada
- `post_publish_hours: [12, 13, 18, 19, 20, 21]` - 6 horas/día (UTC-5)
- `comment_valle_hours: [18, 19, 20, 21, 22, 23, 0, 1]` - 8 horas/día para comentarios valle
- `phase_b_enabled: True` - Fase B activada
- `phase_b_feed_replies: False` - Solo posts propios en Phase B

### 🧠 Quality Governor (Governador de Calidad)

El agente utiliza **5 gates rule-based** (sin calls LLM, 0 costo) para filtrar contenido:

| Gate | Función | Detecta |
|------|---------|---------|
| `text_has_reasoning_leak` | Scaffolds de conclusión | "primero,", "en conclusion", "finalmente," |
| `title_has_scaffold` | Patrones clickbait | "guia completa", "todo sobre", "todo..." |
| `text_has_ungrounded_named_entity` | Entidades sin calificador | "Tesla", "Python" sin "ejemplo/como" |
| `text_has_ungrounded_software_version` | Versiones software sin cal. | "Kafka 0.11", "Python 3.9" |
| `text_has_repeated_example_24h` | Repetición 24h | Mismo texto en últimas 24h |

### 🤖 Cascade de Modelos

**Orden automático de proveedores:**
```
tier_pro (DeepSeek V4 Pro) → tier_fallback (DeepSeek V4) → 
tier_quality (Nemotron free) → openrouter (Nemotron free) → 
huggingface (Mistral/Llama free, HF Inference)
```

**Características clave:**
- ✅ **Circuit breakers** por proveedor con cooldowns diferenciados
- ✅ **DeepSeek 50% descuento** en horas valle (no fines de semana)
- ✅ **Límite diario** configurable vía `DEEPSEEK_SPEND_LIMIT_USD`
- ✅ **Sandbox de pensamiento** desactivado en DeepSeek V4 Pro
- ✅ **Minimum tokens** configurado para quality gate (400 tokens mín.)

### 📡 Telegram Integration

**Modificaciones recientes:**
- `retry_outbox()` se ejecuta al iniciar `listen_for_commands()` 
- `retry_outbox()` se ejecuta al final de cada iteración `while True`
- **Logs:** "Telegram: X mensajes pendientes enviados"
- **Propósito:** Asegura publicación de mensajes en cola pendiente

**Comandos disponibles:**
- `/status` - Estado actual del agente
- `/clean` - Limpieza de recursos
- `/stop` - Detención graceful

### 📅 Horarios de Publicación

**Fase A (Posts Científicos):**
- `post_publish_hours: [12, 13, 18, 19, 20, 21]` (UTC-5, Ecuador)
- **6 horas/día** con mayor engagement
- Fines de semana: **todo el día valle** (50% descuento DeepSeek)

**Fase B (Respuestas):**
- `comment_valle_hours: [18, 19, 20, 21, 22, 23, 0, 1]` (UTC-5, Ecuador)
- **8 horas/día** con descuento DeepSeek
- **Solo posts propios** (`phase_b_feed_replies: false`)

### 📊 Métricas y Tracking

**Archivos de seguimiento:**
- `data/cascade_telemetry.jsonl` - Todas las llamadas LLM (JSONL)
- `data/deepseek_spend_tracker.json` - Gasto diario DeepSeek
- `data/anthropic_spend_tracker.json` - Gasto diario Anthropic
- `data/quota_state.json` - Estado de cuotas por proveedor
- `data/degraded_mode_state.json` - Modo degradado activo?

**Métricas monitoreadas:**
- Posts por día / por ciclo
- Comentarios por día / por post
- Costo USD total y por proveedor
- Tasa de éxito/fallo por proveedor
- Health check del agente

### 🛠️ Comandos Útiles

```powershell
# Verificar estado del agente
python -m scripts.print_daily_report

# Reiniciar agente (graceful)
New-Item data/stop.flag -Force
Start-Sleep -Seconds 2
python run_agent.py

# Ver logs en tiempo real
Get-Content logs\agent.log -Tail 50

# Reset manual gasto DeepSeek (si no se reseteó automáticamente)
# El reset automático ocurre a las 5:00 UTC diariamente
```

### 📜 Historial de Cambios Recientes

**v5.2 (2026-08-24):**
- Remoción del modo dry-run (`data/phase_a_dry_run.flag`)
- Actualización de precios Anthropic: $5.0/$25.0 → $2.0/$10.0
- Configuración de horarios `post_publish_hours` y `comment_valle_hours`
- Agregado `retry_outbox()` en Telegram client
- Quality Governor gates documentados y verificados
- DeepSeek spend limit establecido en $2.00 diarios

**Características removidas:**
- Modo dry-run (consumía tokens innecesariamente)
- Precios Anthropic sobrevalorados ($5.0/$25.0)
- Verificación de horarios inexacta en phase_a_content.py

### 📞 Soporte y Contacto

Para soporte técnico o dudas sobre la configuración:
- Revisar `logs/agent.log` para errores del agente
- Revisar `monitoring/roi_dashboard.py` para métricas financieras
- Revisar `monitoring/telegram-ledger.jsonl` para historial de mensajes
- Revisar `data/deepseek_spend_tracker.json` para control de gastos

---

**⚠️ Recordatorio Importante:**
- El agente opera con `AGENT_PRO_TIER_ONLY=1`, forzando uso de DeepSeek V4 Pro
- Los horarios de publicación (`post_publish_hours`) definen cuándo el agente puede publicar
- El límite diario de DeepSeek es de $2.00, reseteándose automáticamente a las 5:00 UTC
- Los fines de semana todo el día es horario valle (50% descuento)