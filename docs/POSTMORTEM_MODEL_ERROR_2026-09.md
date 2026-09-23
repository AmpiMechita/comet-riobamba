# POST-MORTEM — Incidentes model_error (sep 1, 2, 10 de 2026)
Fecha: 2026-09-23. Origen: P-006. Fuentes: generation_attempts.jsonl, backup-20260920-1844, agent.log.2.

## Resumen
| Día | Count | Topic | source |
|---|---|---|---|
| 2026-09-01 | 661 | silent failure modes in autonomous AI agent loops | forced_fallback |
| 2026-09-02 | 198 | post-mortems of real production failures | dedup_fallback |
| 2026-09-10 | 197 | múltiples | variado |

## 2026-09-10 — Causa raíz
agent.log.2 inicia 04:46:43. Ese minuto el CB de model_cascade tenía los 3 tiers abiertos (flash, fallback, pro). 15.168 WARNINGs model_cascade ese día. Bug adicional en phase_b: "TypeError: can't compare offset-naive and offset-aware datetimes" (82 ocurrencias, todas en agent.log.2). Candidato a fix: 28acb8a, a confirmar.

## 2026-09-01 / 2026-09-02 — Sin logs
agent.log.2 inicia 10-sep, .1 el 18-sep, service_stdout* el 19-sep. Solo queda generation_attempts. 09-01: 661 en ~4h42m (18:05-22:47 UTC), un topic, forced_fallback. 09-02: 198 en ~53min (12:14-13:07 UTC), un topic, dedup_fallback.

## Acciones derivadas
1. Añadir error_type a generation_attempts.
2. Revisar retención de logs (P-056).
3. Confirmar fix 28acb8a.

## Referencias
P-006 en docs/PENDING.md. logs/agent.log.2. backups/generation_attempts.jsonl.backup-20260920-1844.
