# P-082 RE-MEDICION — 2026-09-28

Motivo: auditoria 27/9 reabrio P-082 con "85/120, script borrado, no auditable".
Bloqueador (P-122 cursor-loop) cerrado 28/9. Re-medicion con evidencia reproducible.

## Universo (solo lectura)
data/karma_roi.db comment_actions, 241 filas. NULL score + status=published: 99
  A = 22 own_post_reply action_type=post post_id==comment_id (P-091 legacy)
  B = 63 feed_reply
  C = 14 thread_followup

## Metodo
scripts/recon_p082_backfill.py (efimero, solo lectura API).
A -> get_post(post_id). B/C -> fetch_post_comments(post_id, paginate=True, max_pages=20).

## Resultado (barrido total)
  A: 22/22  B: 63/63  C: 11/14  -> TOTAL 96/99 recuperables.

## 3 MISS = borrados reales
Re-probados con max_pages=20, tamano de lista NO crecio:
  6db7cb37 (post 04f065b7) n=293 estable
  9f3130a4 (post cc631494) n=487 estable
  39f094c4 (post cc631494) n=487 estable
Contraste: falsos negativos previos SI crecieron (75ec581d 772->1105, 71119861 867->1003).

## Hallazgo colateral
services/karma_updater.py::update_karma_from_moltbook usa max_pages=5 por defecto
(tope 250). Posts con >250 en prod (19b6e9bf=1105, 50b2ba76=1737, 84b2c139=1275)
pueden quedar fuera del refresh diario. Pendiente nuevo propuesto: P-129.

## Siguiente paso
Ejecutar backfill real (escritura SQLite) sobre 96 filas. WAL previo. Sin restart.
