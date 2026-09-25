# ADR-004: JSONL obsoleto; SQLite fuente unica de Karma ROI

## Status

Aceptado (2026-09-24). Aprobado por Rafael.

## Context

data/karma_roi_tracker.jsonl coexiste con data/karma_roi.db (SQLite)
desde el diseno v5.3. El docstring de services/karma_roi_tracker.py
declara SQLite fuente de verdad y JSONL compatibilidad hacia abajo.

Inventario 2026-09-24 (sesion P-081) confirmo:

1. Ningun consumidor en produccion lee el JSONL. Solo lo tocan
   monitoring/karma_dashboard.py (CLI manual) y
   services/karma_updater.load_tracker_entries() (uso interno).
2. Cero scripts .ps1/.bat/.cmd/.md operativos lo invocan.
3. Divergencia de schema: JSONL tiene phase, type, total_tokens,
   upvotes_1h, upvotes_24h, comments_received, karma_score; SQLite
   tiene parent_comment_id, target_is_watchlist, status, score,
   last_updated. comments_received es el unico sin equivalente y no
   se consume en ningun sitio (grep 2026-09-24).
4. get_roi_summary ya infiere phase con heuristica
   source=='own_post_reply' (no lee phase del JSONL).
5. engagement_events y daily_snapshots estan vacias desde su
   creacion; la atribucion v5.3 no se implemento en escritura.
## Decision

data/karma_roi.db es la unica fuente de verdad de Karma ROI.
data/karma_roi_tracker.jsonl se declara OBSOLETO y se retirara.

Acciones:

1. Retirar la escritura JSONL de services/karma_roi_tracker.py
   (_jsonl_write_entry y sus 2 call sites, L309 y L700).
2. Eliminar monitoring/karma_dashboard.py (sustituido por
   monitoring/roi_dashboard.py, ya SQLite).
3. services/karma_updater.py deja de leer el JSONL; opera solo
   sobre SQLite via update_karma().
4. Mover data/karma_roi_tracker.jsonl a data/archive/ con timestamp
   (retencion historica, no se borra).
5. tests/conftest.py: retirar monkeypatch de JSONL_PATH y
   KARMA_TRACKER_FILE (deja de existir el archivo).

## Consequences

Positivas:

- Una sola ruta de escritura; elimina la clase de bugs de doble
  escritor (P-074, BUG2/BUG4).
- Elimina la deriva schema JSONL vs SQLite (P-081).
- get_roi_summary deja de depender de heuristica sobre source.

Negativas / deuda aceptada:

- comments_received no se persiste. No hay consumidor; si aparece,
  se agrega columna en SQLite entonces.
- upvotes_1h vs upvotes_24h: hoy update_karma escribe el mismo
  valor en ambos; la granularidad 1h/24h se pierde. Aceptado
  mientras no exista consumidor que la use.
- engagement_events y daily_snapshots siguen vacias; su
  implementacion queda fuera del alcance de P-081 (P-082 la cubre
  parcialmente via backfill).

## Referencias

- services/karma_roi_tracker.py (SCHEMA_SQL, track_action,
  update_karma, get_roi_summary)
- services/karma_updater.py (Camino B, P-079)
- docs/PENDING.md P-081, P-082
- ADR-003 (precedencia topic), ADR-002 (rotacion key)