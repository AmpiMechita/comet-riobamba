<!--
AVISO DE DESACTUALIZACION - 2026-09-11
Los valores de configuracion en este documento NO reflejan la realidad.
Fuente de verdad: docs/CONFIG_TRUTH.md + config/config.py + .env
Este documento se conserva por valor historico, no como referencia tecnica.
-->
# COMET-RIOBAMBA v5.2 - Master Reference Document

> **Canonical project reference for research engineers, agent engineers, SREs, and collaborators.**
> 
> **Version:** evolving (last update: 2026-09-05)
> **Status:** ACTIVE - Modo normal (dry-run removido)

---

## 📋 VERSIONES ANTERIORES

| Version | Fecha | Estado |
|---------|-------|--------|
| v5.0 | 2026-06-17 | Arquitectura inicial |
| v5.1 | 2026-08-01 | Modo dry-run activado |
| **v5.2** | **2026-09-05** | **Modo normal (dry-run removido)** |

---

## 🔧 CONFIGURACIÓN DEL SISTEMA

### .env (Variables de Entorno Críticas)

| Variable | Valor | Descripción |
|----------|-------|-------------|
| `AGENT_PHASE_A_ENABLED` | `1` | Activa Phase A (generación de contenido) |
| `AGENT_PHASE_B_ENABLED` | `1` | Activa Phase B (respuestas/engagement) |
| `AGENT_PHASE_C_ENABLED` | `1` | Activa Phase C (analytics/ métricas) |
| `AGENT_PRO_TIER_ONLY` | `1` | **Forza solo tiers de pago** (DeepSeek). Anthropic se salta al empezar con tier_pro |
| `PHASE_A_GENERATION_TIER` | `pro` | Tier a usar en Phase A: `pro` = DeepSeek V4 Pro |
| `DEEPSEEK_SPEND_LIMIT_USD` | `2.00` | Límite diario de gasto DeepSeek |
| `ANTHROPIC_SPEND_LIMIT_USD` | `2.00` | Límite diario de gasto Anthropic |
| `AGENT_PHASE_A_MODE` | `research` | Modo de generación: `research` (include agenda de investigación) |
| `PHASE_B_FEED_REPLIES` | `false` | **Solo posts propios** en Phase B (sin volumen en feed ajeno) |
| `AGENT_CYCLE_INTERVAL_SECONDS` | `300` | Intervalo base de ciclo (5 minutos) |

### config/behavior_cfg.py

| Configuración | Valor | Descripción |
|-------------|-------|-------------|
| `phase_a_enabled` | `True` | Activa Phase A |
| `phase_b_enabled` | `True` | Activa Phase B |
| `post_publish_hours` | `[12, 13, 18, 19, 20, 21]` | Horas UTC para publicación Phase A (6h/día, UTC-5) |
| `comment_valle_hours` | `[18, 19, 20, 21, 22, 23, 0, 1]` | Horas UTC para comentarios valle Phase B (8h/día, UTC-5) |
| `phase_b_feed_replies` | `false` | **Solo responder en posts propios** (sin volumen en feed ajeno) |
| `phase_b_max_replies` | `1` | Máximo replies por ciclo Phase B |
| `cycle_interval_seconds` | `28800` | Intervalo base de ciclo (8 horas) |
| `max_posts_per_day` | `5` | Techo duro de posts por día |
| `posts_per_day` | `1` | Objetivo diario de posts |

### 🤖 Fallback Chain de Modelos (CON AGENT_PRO_TIER_ONLY=1)

**Orden REAL de provisión (lo que el agente usa por defecto):**

```
1. tier_pro (DeepSeek V4 Pro) ← **Forzado por AGENT_PRO_TIER_ONLY=1**
2. tier_fallback (DeepSeek V4) ← Siguiente en cascade
3. tier_quality (Nemotron 120B free, OpenRouter) ← Gratuito
4. openrouter (Nemotron free) ← Gratuito
5. huggingface (Mistral-7B/Llama-3-8B free, HF Inference) ← Gratuito
```

**Notas importantes:**
- `tier_premium` (Anthropic Claude) **NO se usa** cuando `AGENT_PRO_TIER_ONLY=1`
- El agente empieza con `tier_pro` y si falla, baja al siguiente en cascade
- Los tiers gratuitos (`tier_quality`, `openrouter`, `huggingface`) son gratuitos pero tienen límites

**Fallback Chain ANTIGUA (sin AGENT_PRO_TIER_ONLY=1):**
```
tier_premium (Anthropic) → tier_fallback (DeepSeek) → tier_pro → tier_quality → openrouter → huggingface
```

### 💰 Precios por 1M de Tokens

| Tier | Input/1M | Output/1M | Estado | Comentario |
|------|----------|-----------|--------|------------|
| `tier_premium` (Anthropic) | $5.00 | $25.00 | **Desusado** | Ya no se usa con AGENT_PRO_TIER_ONLY=1 |
| `tier_fallback` (DeepSeek V4) | $1.32 | $3.96 | **Activo** | 50% descuento en horas valle |
| `tier_flash` (Gemini) | $0.075 | $0.30 | **Dead** | Sin usar, fallback profundo |
| `tier_pro` (DeepSeek V4 Pro) | $1.32 | $3.96 | **Activo** | Preferido cuando AGENT_PRO_TIER_ONLY=1 |
| `tier_quality` (Nemotron) | $0.0 | $0.0 | **Gratis** | OpenRouter / HF Inference |
| `openrouter` (Nemotron) | $0.0 | $0.0 | **Gratis** | Mismo modelo que tier_quality |
| `huggingface_flash` (Mistral) | $0.0 | $0.0 | **Gratis** | HF Inference |
| `huggingface_fallback` (Llama) | $0.0 | $0.0 | **Gratis** | HF Inference |

### 📅 Horarios de Publicación (UTC-5, Ecuador)

**Fase A - Post Generation:**
- `post_publish_hours: [12, 13, 18, 19, 20, 21]`
- **6 horas/día** con mayor engagement esperado
- **Fin de semana = todo valle** (desde 23/ago/2026)
  - Sábado domingo: 100% descuento DeepSeek

**Fase B - Community Replies:**
- `comment_valle_hours: [18, 19, 20, 21, 22, 23, 0, 1]`
- **8 horas/día** con descuento DeepSeek
- `phase_b_feed_replies: false` - **Solo posts propios**

### ⚙️ Quality Governor (Governador de Calidad)

**5 gates rule-based (SIN calls LLM, 0 costo):**

| Gate | Función | Detecta | Retorna |
|------|---------|---------|---------|
| `text_has_reasoning_leak` | Scaffolds de conclusión | "primero,", "en conclusion", "finalmente," | `(bool, str)` - `(True, razón)` si error |
| `title_has_scaffold` | Patrones clickbait | "guia completa", "todo sobre", "todo..." | `(bool, str)` |
| `text_has_ungrounded_named_entity` | Entidades sin calificador | "Tesla", "Python" sin "ejemplo/como" | `(bool, str)` |
| `text_has_ungrounded_software_version` | Versiones software sin cal. | "Kafka 0.11", "Python 3.9" | `(bool, str)` |
| `text_has_repeated_example_24h` | Repetición 24h | Mismo texto en últimas 24h | `(bool, str)` |

**Resultado:** `(aprobado: bool, razon: str)`
- `aprobado=True` → contenido pasa, puede publicarse
- `aprobado=False` → contenido bloqueado, razón explicada

**Umbrales adicionales (artistic_excellence):**
- `variance < 400` → reject (poca variación en oraciones)
- `sentence ≤ 15 words` → reject (sin punchline)
- `sin contraste (not/but/yet)` → reject (sin paradoja/contrast)

### 🔌 Telegram Integration

**Modificaciones recientes (2026-09-05):**
- `retry_outbox()` en `listen_for_commands()` - **al inicio** (después de `if not self.enabled: return`)
- `retry_outbox()` al final de cada iteración `while True` (después de `await asyncio.sleep(3)`)
- **Logs:** `"Telegram: X mensajes pendientes enviados"`
- **Propósito:** Asegura que mensajes en cola pendiente se publiquen

**Comandos disponibles por Telegram:**
- `/status` - Estado actual del agente (posts hoy, fase, etc.)
- `/clean` - Limpieza de recursos temporales
- `/stop` - Detención graceful (crea `data/stop.flag`)

**Estado del agente en mensajes Telegram:**
- `"🔥 Engagement spike! Post X tiene Y comments — debate activo"`
- `"📝 POST GENERADO (Phase A)"` - **(YA NO MÁS - modo normal)**
- `"💸 Gasto LLM de hoy: $X.XXX | Llamadas: N"`
- `"📊 Stats hoy (YYYY-MM-DD): Comments: N, Upvotes: N, Follows: N, Searches: N"`
- `"👥 Referentes Watchlist en posts de COMET: N comentario(s)"`
- `"🔧 Health Check: Cycle: N, Posts hoy: N, Comments hoy: N, Failures: 0"`
- `"🔥 Engagement spike! Post X tiene Y comments — debate activo"`
- `"⚠️ Quality Governor REJECTED (razón)"`
- `"🧪 DRY-RUN Phase A ACTIVO: NO se publica post real"` - **(YA NO MÁS - removido)**

### 🧠 Circuit Breakers (Interruptores Circuito)

Cada proveedor tiene su propio CircuitBreaker con cooldowns diferenciados:

| Error Type | Duración force-open | Descripción |
|------------|---------------------|-------------|
| Sin crédito (402 / freeusagelimit) | 12h (43200s) | DeepSeek sin saldo, fuerza circuito abierto |
| Rate limit (429) | 1h (3600s) | Evita latencia excesiva |
| Error cliente (401/403) | 5m (300s) | Credenciales inválidas o bloqueadas |
| Default | conteo normal, OPEN umbral 3 fallos | Circuit breaker normal |

**Flujo cuando un proveedor falla:**
1. `_record_failure(provider, error)`
2. `_classify_http_error(error)` → `"rate_limit"`, `"client"`, `"server"`, `"network"`, `"unknown"`
3. Según tipo: fuerza OPEN por duración específica
4. Siguiente proveedor en cascade automáticamente
5. Si todos fallan → `_enter_degraded_mode()`
   - Modo degradado, alerta Telegram cada cooldown (30 min default)

### 📊 Tracking y Monitoreo

**Archivos de persistencia principal:**

| Archivo | Contenido | Actualización |
|---------|-----------|--------------|
| `data/cascade_telemetry.jsonl` | **TODAS** las llamadas LLM (JSONL) | Cada ciclo |
| `data/deepseek_spend_tracker.json` | Gasto diario DeepSeek `{date, total_usd}` | Diario (resetea automáticamente o manual) |
| `data/anthropic_spend_tracker.json` | Gasto diario Anthropic `{date, total_usd}` | Diario |
| `data/quota_state.json` | Estado de cuotas por proveedor | Cada ciclo |
| `data/degraded_mode_state.json` | Modo degradado `{is_degraded, since_ts, last_alert_ts}` | Persistente |

**Métricas monitoreadas en cada ciclo:**
- Posts hoy / por ciclo
- Comentarios hoy / por post
- Costo USD total y por proveedor
- Tasa de éxito/fallo por proveedor
- Health score por proveedor (historial últimoas 10 iteraciones)
- Circuit breaker state por proveedor

### 📊 Métricas Reportadas por Telegram

- `"📊 Stats hoy (YYYY-MM-DD): Comments: N, Upvotes: N, Follows: N, Searches: N"`
- `"💸 Gasto LLM de hoy: $X.XXX | Llamadas: N"`
- `"👥 Referentes Watchlist en posts de COMET: N comentario(s)"`
- `"🔧 Health Check: Cycle: N, Posts hoy: N, Comments hoy: N, Failures: 0"`
- `"🔥 Engagement spike! Post X tiene Y comments — debate activo"`

### 📜 Historial de Cambios (v5.2 - 2026-09-05)

| Cambio | Descripción | Impacto |
|--------|-------------|---------|
| **Modo dry-run removido** | `data/phase_a_dry_run.flag` eliminado | El agente publica realmente en Moltbook |
| **Precios Anthropic actualizados** | $5.0/$25.0 → $2.0/$10.0 | Coincide con model_cascade.py |
| **Horarios configurados** | `post_publish_hours` y `comment_valle_hours` | Definidos explícitamente (UTC-5) |
| `retry_outbox()` en Telegram | 2 lugares en `listen_for_commands()` | Asegura publicación de mensajes pendientes |
| **Quality Governor verificado** | 5 gates rule-based, 0 costo LLM | Confirmado con 428+ rechazos en logs |
| **Fallback chain actualizada** | `tier_pro → tier_fallback → gratis` | Refleja `AGENT_PRO_TIER_ONLY=1` |
| **DeepSeek spend limit** | Establecido en $2.00/día | Reset automático a las 5:00 UTC |
| **Quality Governor verificado** | 5 gates, 428+ rechazos detectados | Sin consumo de tokens LLM |

### 📋 Próximos Pasos Sugeridos

1. **Monitorear gasto diario** - Verificar `data/deepseek_spend_tracker.json` diario
2. **Poblar watchlist** - `config/top_agents_watchlist.json` (0 agentes actuales)
3. **Estandarizar timezone** - Verificar consistencia `datetime.now(timezone.utc)` vs `datetime.now()`
4. **Expandir watchlist** - Agregar agentes reputados para engagement prioritized
5. **Optimizar thresholds** - Quality Governor thresholds basados en datos reales

### 📞 Soporte y Contacto

- **Logs:** `logs/agent.log` - Errores y operaciones del agente
- **Telegram ledger:** `monitoring/telegram-ledger.jsonl` - Historial de mensajes
- **Métricas:** `monitoring/roi_dashboard.py` - Métricas financieras en tiempo real
- **Gastos:** `data/deepseek_spend_tracker.json` y `data/anthropic_spend_tracker.json`

**⚠️ Recordatorio Crítico:**
- `AGENT_PRO_TIER_ONLY=1` fuerza uso de DeepSeek V4 Pro (no Anthropic)
- `DEEPSEEK_SPEND_LIMIT_USD=2.00` - Límite diario, resetea automáticamente a las 5:00 UTC
- `phase_a_dry_run.flag` **FUE REMOVIDO** - El agente publica realmente en Moltbook
- `post_publish_hours` define cuándo el agente puede publicar (UTC-5, Ecuador)
- `phase_b_feed_replies: false` - Solo responder en posts propios, sin volumen en feed ajeno

---
**Última actualización: 2026-09-05 por agente forense**