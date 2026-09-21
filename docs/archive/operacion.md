<!--
AVISO DE DESACTUALIZACION - 2026-09-11
Los valores de configuracion en este documento NO reflejan la realidad.
Fuente de verdad: docs/CONFIG_TRUTH.md + config/config.py + .env
Este documento se conserva por valor historico, no como referencia tecnica.
-->
# Guía de Operación — COMET-RIOBAMBA

## 1. Visión general operativa

COMET-RIOBAMBA es un agente autónomo que opera en **Moltbook** ejecutando un pipeline cíclico de tres fases:

- **Fase A**: genera y publica contenido técnico original (posts).
- **Fase B**: responde a comentarios — tanto en feed ajeno como en posts propios — respetando cuotas diarias, por ciclo y por post.
- **Fase C**: analiza métricas de rendimiento y genera insights de optimización.

El agente está diseñado para operar 24/7. Cada ciclo ejecuta las fases habilitadas en secuencia, respetando límites diarios y de frecuencia. La observabilidad se basa en **eventos estructurados** que alimentan un sistema de métricas diarias.

---

## 2. Métricas diarias

Cada día calendario se genera un archivo en `data/metrics/YYYY-MM-DD.json` con un resumen numérico de la actividad del agente.

### Contadores principales

| Campo | Significado |
|---|---|
| `cycle_count` | Número de ciclos ejecutados en el día |
| `posts_published` | Posts publicados exitosamente por Fase A |
| `posts_skipped_daily_limit` | Veces que Fase A no ejecutó por límite diario alcanzado |
| `comments_published` | Comentarios publicados exitosamente por Fase B |
| `comments_skipped_daily_limit` | Comentarios saltados por límite diario de comentarios |
| `comments_skipped_per_cycle_limit` | Comentarios saltados por límite por ciclo |
| `comments_skipped_per_post_limit` | Comentarios saltados por límite por post/hilo |
| `comments_skipped_low_relevance` | Comentarios saltados por baja relevancia (score < umbral) |
| `comments_near_duplicate_skipped` | Comentarios saltados por ser casi duplicados del anterior en el mismo hilo |
| `comment_outbox_retried` | Comentarios del outbox que se reintentaron y publicaron |
| `outbox_posts_retried` | Posts del outbox que se reintentaron y publicaron |
| `phase_c_runs` | Veces que Fase C ejecutó analytics |
| `errors_total` | Errores totales registrados en ciclos |
| `consecutive_failures` | Fallos consecutivos al final del día |
| `last_cycle_duration_avg_s` | Duración promedio de ciclo en segundos |

### Persistencia

- Ruta: `data/metrics/`
- Formato: un archivo JSON por día (`2026-06-09.json`)
- Actualización: cada evento escribe el archivo inmediatamente
- Lectura: el script de reporte carga el archivo del día solicitado

---

## 3. Cómo leer el reporte diario

### Comando

```powershell
python -m scripts.print_daily_report          # hoy
python -m scripts.print_daily_report 2026-06-09  # fecha específica
```

### Ejemplo de salida

```
Fecha: 2026-06-09
Ciclos ejecutados: 5
Posts publicados: 1 (4 bloqueados por límite diario)
Comentarios publicados: 6
Comentarios bloqueados (día/ciclo/post/relevancia/dup): 2 / 3 / 1 / 5 / 0
Outbox posts reintentos: 0
Outbox comments reintentos: 1
Fase C ejecuciones: 0
Errores totales: 0
Consecutive failures: 0
Duración promedio ciclo (s): 132.5
```

### Interpretación rápida

- **Posts publicados == 1 y Ciclos > 1**: normal si `max_posts_per_day=1`. El resto de ciclos se saltan por límite diario.
- **Comentarios bloqueados altos**: puede indicar que hay muchos posts con baja relevancia o que las cuotas están siendo muy restrictivas.
- **Errores totales > 0**: revisar logs del día para identificar la causa.
- **Consecutive failures > 3**: el agente podría auto-pausarse. Revisar conectividad con Moltbook o LLM.

### Ver últimos N días

```powershell
python -m scripts.metrics_last_n_days           # últimos 7
python -m scripts.metrics_last_n_days --days 14 # últimos 14
```

---

## 4. Playbook de incidentes

### 4.1 Pocos posts (0 en un día teniendo ciclos)

**Síntomas**: `posts_published=0`, `cycle_count>0`.

**Métricas a mirar**:
- `posts_skipped_daily_limit`: si es > 0 y `posts_published=0`, el estado de `posts_today` pudo haber empezado ya en el límite.
- `errors_total`: si hay errores, revisar logs de Fase A.
- Logs: buscar `FASE A:` y `daily_limit_reached` o `error generando`.

**Acciones**:
1. Verificar `AGENT_MAX_POSTS_PER_DAY` en `.env` (valor recomendado: 1–3).
2. Verificar conectividad con Moltbook (`MOLTBOOK_API_KEY` vigente).
3. Verificar conectividad con el modelo LLM (Ollama/cloud).
4. Forzar un ciclo manual: `python -m core.agent` en modo interactivo.

---

### 4.2 Demasiados posts (más de lo esperado)

**Síntomas**: `posts_published > AGENT_MAX_POSTS_PER_DAY` en un mismo día.

**Métricas a mirar**:
- Verificar que el archivo de métricas no tenga datos de varios días fusionados.
- Revisar `cycle_start` y `cycle_end` en logs para ver si hay ejecuciones duplicadas.

**Acciones**:
1. Verificar que no haya múltiples instancias del agente corriendo en paralelo.
2. Revisar que `AGENT_MAX_POSTS_PER_DAY` esté correctamente seteado en `.env`.
3. Verificar que `data/state/comet_state.db` no esté corrupto (hacer backup y borrar para reiniciar contadores).
4. **Nunca** modificar manualmente el archivo de métricas; el estado real está en SQLite.

---

### 4.3 Pico de comentarios publicados

**Síntomas**: `comments_published` mucho más alto que el promedio histórico.

**Métricas a mirar**:
- `comments_skipped_daily_limit`: si es 0, las cuotas no están frenando.
- `comments_skipped_low_relevance`: si es bajo, tal vez el umbral de relevancia está muy permisivo.

**Acciones**:
1. Revisar `AGENT_MAX_COMMENTS_PER_DAY` en `.env` (valor recomendado: 5–10).
2. Revisar `AGENT_MAX_COMMENT_REPLIES_PER_CYCLE` (valor recomendado: 1–3).
3. Si hay muchas respuestas a posts de baja calidad, ajustar `min_comment_relevance_score` en `config/agent_policy.py`.

---

### 4.4 Muchos comentarios saltados

**Síntomas**: `comments_skipped_low_relevance` alto.

**Métricas a mirar**:
- Distribución entre `daily_limit`, `per_cycle_limit`, `per_post_limit`, `low_relevance`.

**Acciones**:
1. Si `low_relevance` es dominante: el feed puede tener mucho contenido no técnico o el umbral está muy alto.
2. Si `daily_limit` es dominante: el agente ya alcanzó el techo diario. Es normal.
3. Si `per_cycle_limit` es dominante: el agente está encontrando muchos comentarios relevantes pero no puede responderlos todos en un ciclo. Considerar aumentar `AGENT_MAX_COMMENT_REPLIES_PER_CYCLE`.
4. Si `per_post_limit` es dominante: hay hilos muy activos. El límite de 3 respuestas por hilo es razonable.

---

### 4.5 Errores frecuentes

**Síntomas**: `errors_total > 0` sostenido en varios días.

**Métricas a mirar**:
- `consecutive_failures`: si llega a 3+, el agente debería auto-pausarse y notificar por Telegram.
- Logs del día con grep: `grep -i "error\|exception\|traceback" logs/agent.log`.

**Acciones**:
1. Verificar conectividad a Internet y disponibilidad de Moltbook.
2. Verificar que el modelo LLM esté respondiendo (Ollama: `ollama list`, cloud: revisar API key).
3. Si `consecutive_failures >= 3` y no hay notificación Telegram, revisar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
4. Como último recurso: borrar `data/state/comet_state.db` (resetea contadores) y reiniciar.

---

### 4.6 Duración de ciclo anormal

**Síntomas**: `last_cycle_duration_avg_s` muy alta (> 300s) o muy baja (< 10s).

**Métricas a mirar**:
- `cycle_count`: comparar con días anteriores.
- Logs: revisar tiempos entre `CICLO N INICIADO` y `CICLO N FINALIZADO`.

**Acciones**:
1. Si es muy alta: el LLM puede estar tardando en responder (timeouts, modelo lento). Revisar conectividad con el proveedor.
2. Si es muy baja: puede que el agente esté saltando fases (por ejemplo, todas saltadas por límite diario). Revisar `phase_a_publish_skip` en logs.

---

## 5. Parámetros críticos de configuración

### Variables de entorno (`.env`)

| Variable | Default | Recomendado | Rango válido |
|---|---|---|---|
| `AGENT_MAX_POSTS_PER_DAY` | 1 (POLICY) | 1–3 | 1–10 |
| `AGENT_MAX_COMMENTS_PER_DAY` | 6 | 5–10 | 0–50 |
| `AGENT_MAX_COMMENT_REPLIES_PER_CYCLE` | 1 | 1–3 | 0–10 |
| `AGENT_MAX_COMMENTS_PER_POST` | 3 | 1–3 | 0–10 |
| `AGENT_CYCLE_INTERVAL_SECONDS` | 28800 (8h) | 14400–43200 | — |
| `AGENT_PHASE_B_ENABLED` | 0 | 1 para activar | 0/1 |
| `AGENT_WHISPER_MODE` | 0 | 0 en producción | 0/1 |

### Cómo cambiar valores

1. Editar `.env` en la raíz del proyecto.
2. La sobreescritura valida rangos automáticamente (ver `config/config.py:_validate_bounded_int`).
3. Si el valor está fuera de rango, se usa el default de `POLICY` y se loggea una advertencia.
4. **No es necesario reiniciar el proceso** si el agente lee la configuración en cada ciclo (lo hace mediante `behavior_cfg`).

### Cómo ver la configuración efectiva

Buscar en los logs mensajes como:

```
config.config | ⚠ AGENT_MAX_POSTS_PER_DAY=15 excede el máximo 10. Usando POLICY: 1
```

Si no hay advertencias, la configuración生效 es la del `.env`.

---

## 6. Referencias

- `docs/README_COMET.md` — arquitectura técnica y diseño de fases
- `docs/RUNBOOK_AGENT.md` — comandos de inicio y operación
- `core/metrics.py` — implementación del sistema de métricas
- `core/observability.py` — sistema de eventos
- `scripts/print_daily_report.py` — script de reporte diario
- `scripts/metrics_last_n_days.py` — resumen de últimos N días
