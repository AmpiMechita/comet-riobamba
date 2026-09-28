# HANDOFF - 2026-09-27 (sesion auditoria)
Sesion 2026-09-27. Op Rafael. Motivo: auditoria sistematica cierres p079-p119.
HEAD al abrir: bba68de. HEAD al cerrar: este commit.

## 1. Que se hizo
- Auditoria 22 pendientes en 6 fases (AUD-1..AUD-6).
- H1: fetch_post_comments ignora next_cursor, solo pagina 1.
- P-088 refutado: 3/3 irrecuperables recuperables con cursor.
- P-082 reabierto: script _p088_backfill.py borrado, no auditable.
- P-115: veredicto REJECTED correcto, descripcion PENDING incorrecta.
- Alta P-122 (fix cursor) y P-123 (MAPA_TECNICO ADRs).

## 2. Cobertura
21/22 con evidencia (185 tests ejecutados, numstat ok). P-082 no auditable.
AUD-1 commits<->P-XXX: PASA
AUD-2 numstat declarado vs real: PASA
AUD-3 tests citados existen y pasan: PASA
AUD-4 paths/DBs citados: PASA
AUD-5 premisas REJECTED: P-115 correcto, errata doc
AUD-6 dependientes fetch_post_comments: 5 componentes afectados

## 3. Hallazgos
H1 Bug activo cursor. L624 ignora has_more/next_cursor; API ignora offset. Probe real: 527 cmts/11 pags.
H2 Afectados: karma_updater.update_karma_from_moltbook (P-074/P-079), comment_votes.refresh_all_comment_votes (loop roto en pg2), matcher follow-ups (orchestrator 2165/3910/4192), telegram_client:550, phase_c_analytics:93.
H3 P-088 falso negativo: 3/3 probados recuperables.
H4 P-082 no auditable: script borrado, numeros no reproducibles.
H5 P-115 descripcion incorrecta: NO hay bug. Asignacion DB_PATH=args.db a nivel modulo, --db SI tiene efecto.
H6 MAPA_TECNICO sin ADR-004/005.
H7 Limpieza sesion: 5 probes + karma_roi_tracker.db(0B) borrados.

## 4. Deuda nueva
P-122 (Alta): soporte cursor en fetch_post_comments, 13 callers.
P-123 (Baja): MAPA_TECNICO ADR-004/005.
P-082/P-088 reabiertos con nueva redaccion.

## 5. Sugerencia proxima sesion
P-122 (~2h): implementar cursor-loop opt-in, mapear callers, test.
Alternativas: P-120 (cwd-relativo), P-121 (test --db).

## 6. Estado tras sesion
HEAD: este commit. CometRiobamba Running, sin reinicio. Working tree limpio.


## 7. Restricciones de diseno para P-122 (no perder)

P-122 (soporte cursor en fetch_post_comments) debe respetar:

- OPT-IN. Por defecto `paginate=False`, una sola pagina. Los 13 callers
  actuales NO cambian de comportamiento. El bucle de cursor solo se activa
  donde se justifique (parametro explicito o metodo nuevo
  `fetch_all_post_comments`).
- RIESGO DE BLAST RADIUS. Un post grande puede tener 500+ comentarios
  (verificado hoy: 527 top-level en 11 paginas para 19b6e9bf-6ff9-4ea5-834a-cbbac714f546). Paginar por
  defecto multiplica llamadas HTTP x11 en cada ciclo del agente -> riesgo
  de rate-limit Moltbook -> ciclo perdido -> produccion rota.
- CALLERS PRIORITARIOS (migrar primero, con test dirigido):
  1) services/karma_updater.py:59 (lazo de karma; P-074/P-079).
  2) services/comment_votes.py:107 (loop roto en pagina 2; el propio codigo
     admite "la API ignora el offset" pero nunca busco cursor).
  Despues: matcher follow-ups orchestrator.py 2165/3910/4192.
  Solo con evidencia: telegram_client:550, phase_c_analytics:93.
- TESTS. Un test unitario por caller migrado (stub del cliente que devuelve
  2 paginas y confirma que el bucle las recorre). Un test del default
  (paginate=False) que confirme comportamiento actual sin cambios.
- RE-MEDIR P-082. Solo despues de mergear P-122 tiene sentido reabrir el
  conteo de "cuantos backfills son recuperables"; el numero "85/120" del
  ledger queda marcado como no auditable hasta entonces.
