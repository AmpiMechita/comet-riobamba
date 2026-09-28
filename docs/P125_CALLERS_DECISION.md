# P-125 — Decision por caller (fetch_post_comments paginado)
Fecha: 2026-09-28 (p125). Probe real contra API sobre top-3 posts con
comentarios nuestros. Refuta "todos los callers ganan".
## Evidencia
| post | ours | p1 | all | onlyP2 | MISSING_OURS |
|---|---|---|---|---|---|
| 098c963a | 50 | 278 | 278 | 0 | 0 |
| 1920b62f | 50 | 435 | 1111 | 676 | 0 |
| 703754c3 | 43 | 134 | 134 | 0 | 0 |
MISSING_OURS=0: nuestros comentarios caen en pagina 1. onlyP2=676 en
1920b62f: comentarios de OTROS invisibles a paginate=False.
## Decision
| caller | veredicto | razon |
|---|---|---|
| orchestrator:3910 | MIGRAR | pool real oculto; sin techo. |
| orchestrator:4192 | NO | sin caller prod (solo tests) -> P-127. |
| orchestrator:2165 | NO | MISSING_OURS=0; log replies_matched=4. |
| phase_c:93 | NO | 3 posts, pagina 1 cubre. |
| telegram_client:550 | NO | manual; trunca [:5]. |
## Cambio
En _execute_own_post_replies:
  comment_count > 50 -> paginate=True, max_pages=3
  resto              -> paginate=False (historico)