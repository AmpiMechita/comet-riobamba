# CONFIG_TRUTH.md — Fuente de verdad de configuración

> Actualizado: 2026-09-17.
> Estado REAL de la configuración en producción.
> Si algo contradice este documento, actualizar aquí primero.

---

## 0. Spend guard DeepSeek — ACTIVO desde 2026-09-13

**Estado:** implementado y operativo (Fase 5 de la auditoría).

### Implementación en `services/model_cascade.py`
- `_is_deepseek_direct(provider)` — static; excluye URLs con opencode.ai o /zen/.
- `_deepseek_spend_limit()` — lee `DEEPSEEK_SPEND_LIMIT_USD` del .env; default 0.50.
- `_get_deepseek_spend()` — lee `data/deepseek_spend_tracker.json`; reset implícito si fecha != hoy UTC.
- `_record_deepseek_spend(provider, in, out)` — acumula coste con precios PEAK como cota superior.
- `_call_provider_once()` — guard bloquea si gasto >= cap SIN tocar la API.

### Valor actual en `.env` (2026-09-17)
`DEEPSEEK_SPEND_LIMIT_USD=0.5`

### Verificación
- `tests/test_deepseek_spend_guard.py`: 5/5 PASS.
- Tracker vivo: `data/deepseek_spend_tracker.json` acumula diariamente.

---

## 8. Costos reales medidos (histórico)

### Medición 2026-09-02 (Lecciones Aprendidas)
- Post Fase A: ~$0.001054 USD (1,078 tokens promedio)
- Comentario Fase B: ~$0.001022 USD (1,259 tokens promedio)
- Proyección mensual teórica: ~$3.69 USD

### Medición 2026-09-06 a 2026-09-10 (audit_spend_from_logs.py)
- Total: $1.56 USD en 5 días (~$0.31/día)
- Desglose: $1.32 vino de tier_fallback (bug de orden invertido)
- Sin el bug: ~$0.10-0.15/día → coincide con la proyección del 2/9

### Implicación
El gasto normal del agente en producción sana es ~$0.10-0.15/día.
El bug de tier_fallback multiplicó el gasto por ~3x entre el 6 y el 10 de septiembre.

### Techo recomendado
- Conservador: $0.25/día (2x operación normal)
- Recomendado: $0.35/día (2.3x operación normal)
- Con holgura: $0.50/día (3.3x operación normal)

**Valor aplicado:** $0.50/día (`.env`).

---

## 9. Historia del spend limit

### Intento 1 — quota_manager.py (pre-2/9/2026)
- Bug: sobre-contaba llamadas (reportó $5.00 cuando gasto real era $1.94).
- Estado actual: desactivado vía `DEEPSEEK_SPEND_LIMIT_USD=999999` en docs. Fósil.

### Intento 2 — `_deepseek_spend_limit` en tests (2026-09-XX)
- Existía en tests con valor $0.50; no en producción.

### Intento 3 — Fase 5 auditoría — CERRADO 2026-09-13
- Implementado en `services/model_cascade.py` (ver §0).
- Referencia: `docs/AUDIT_PROGRESS.md` sección "Fase 5 — DeepSeek spend guard".

---

## 10. Valores históricos de DEEPSEEK_SPEND_LIMIT_USD

| Valor | Origen | Estado |
|---|---|---|
| 999999 | Intento 1 (2/9/2026), para desactivar quota_manager | Fósil histórico |
| 0.00 | Intento pre-2/9 (no documentado) | Fósil histórico |
| 0.5 | `.env` actual, aplicado por Fase 5 (2026-09-13) | **ACTIVO** |
---

## 11. Scheduling day-aware (2026-09-19)

Helpers en `config/schedule.py`: get_quiet_hours/post_hours/comment_hours + get_max_posts_per_day/comments_per_day. Si es sab/dom y existe `*_WEEKEND` en `.env`, se usa. Si no, weekday.

Vars weekend: `AGENT_QUIET_HOURS_WEEKEND`, `AGENT_POST_HOURS_WEEKEND`, `AGENT_COMMENT_HOURS_WEEKEND`, `AGENT_MAX_POSTS_PER_DAY_WEEKEND=2`, `AGENT_MAX_COMMENTS_PER_DAY_WEEKEND=40`.

## 12. Trazabilidad: run_id

- Phase A (985cd2f): `run_id=cycle-N-<unix_ts>` en `generation_attempts.jsonl`.
- Auto-apply (6717543): `run_id` + `ts` (epoch) + `timestamp` (ISO UTC) en `proposal_apply_log.jsonl`.

Regla #31: toda metrica persistida entre arranques debe incluir run_id.

## 13. Allowlist auto-mejora

`config/auto_appliable.py::ALLOWLIST`. Ver el archivo para valores actuales (7 params, min=2 en `max_comment_replies_per_cycle`). Overlay activo: `data/auto_applied_config.json`. Regla #36: min>0 si 0 desactiva una fase.

---

*Actualizado: 2026-09-20.*
