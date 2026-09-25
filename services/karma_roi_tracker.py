# -*- coding: utf-8 -*-
"""
Karma ROI Tracker - SQLite persistence per diseño v5.3.

Ruta de base de datos: data/karma_roi.db
Tablas: comment_actions, engagement_events, daily_snapshots

Sigue el diseño especificado en la documentación ROI_TRACKING.md.
Proporciona compatibilidad hacia atrás con firmas de funciones existentes
mientras usa SQLite como fuente de verdad.
"""

import sqlite3
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "karma_roi.db"
JSONL_PATH = BASE_DIR / "data" / "karma_roi_tracker.jsonl"

SCHEMA_SQL = """
-- Tabla: comment_actions
-- Almacena cada acción de comentario o post con su costo y metadatos.
CREATE TABLE IF NOT EXISTS comment_actions (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    parent_comment_id TEXT NULL,
    target_author TEXT NULL,
    target_is_watchlist INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,              -- own_post_reply | thread_followup | feed_reply
    score REAL NULL,
    model TEXT NULL,
    tier TEXT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_updated TEXT,                 -- timestamp de última actualización
    status TEXT NOT NULL               -- published | rejected | duplicate | failed
);

-- Tabla: engagement_events
-- Registra eventos de interacción (upvote, reply, follow) atribuibles.
CREATE TABLE IF NOT EXISTS engagement_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_comment_id TEXT NULL,
    action_post_id TEXT NULL,
    actor TEXT NULL,
    actor_is_watchlist INTEGER NOT NULL DEFAULT 0,
    event_type TEXT NOT NULL,          -- comment_reply | upvote | follow | post_reply
    event_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    attribution_method TEXT NOT NULL,  -- direct_comment | same_post_window | aggregate_only
    UNIQUE(action_comment_id, actor, event_type, event_at)
);

-- Tabla: daily_snapshots
-- Captura diario de métricas resumidas.
CREATE TABLE IF NOT EXISTS daily_snapshots (
    date TEXT PRIMARY KEY,
    karma INTEGER NULL,
    posts_today INTEGER NOT NULL DEFAULT 0,
    comments_today INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);
"""

# Mapeo de nombres de estado para consistencia
VALID_STATUSES = {"published", "rejected", "duplicate", "failed"}
VALID_EVENT_TYPES = {"comment_reply", "upvote", "follow", "post_reply"}
VALID_ATTRIBUTION_METHODS = {"direct_comment", "same_post_window", "aggregate_only"}


def _get_conn() -> sqlite3.Connection:
    """Obtiene conexión a la base de datos SQLite, creando tablas si es necesario."""
    db_path = DB_PATH if isinstance(DB_PATH, Path) else Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 3000")  # 3 segundos timeout en busy
    conn.executescript(SCHEMA_SQL)
    return conn


# ═══════════════════════════════════════════════════════════════
# Persistencia SQLite (fuente de verdad)
# ═══════════════════════════════════════════════════════════════

def _sql_insert_comment_action(conn: sqlite3.Connection, entry: Dict[str, Any]) -> None:
    """Inserta o reemplaza una entrada en comment_actions."""
    conn.execute(
        """INSERT OR REPLACE INTO comment_actions
        (comment_id, post_id, parent_comment_id, target_author, target_is_watchlist,
         source, score, model, tier, input_tokens, output_tokens, cost_usd,
         created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.get("comment_id"),
            entry.get("post_id"),
            entry.get("parent_comment_id"),
            entry.get("target_author"),
            int(entry.get("target_is_watchlist", 0)) if entry.get("target_is_watchlist") is not None else 0,
            entry.get("source"),
            entry.get("score"),
            entry.get("model"),
            entry.get("tier"),
            int(entry.get("input_tokens", 0)) if entry.get("input_tokens") is not None else 0,
            int(entry.get("output_tokens", 0)) if entry.get("output_tokens") is not None else 0,
            float(entry.get("cost_usd", 0)) if entry.get("cost_usd") is not None else 0.0,
            entry.get("created_at"),
            entry.get("status"),
        ),
    )
    conn.commit()


def _sql_insert_engagement_event(conn: sqlite3.Connection, entry: Dict[str, Any]) -> None:
    """Inserta un evento de engagement con deduplicación por UNIQUE constraint."""
    conn.execute(
        """INSERT OR IGNORE INTO engagement_events
        (action_comment_id, action_post_id, actor, actor_is_watchlist,
         event_type, event_at, observed_at, attribution_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.get("action_comment_id"),
            entry.get("action_post_id"),
            entry.get("actor"),
            int(entry.get("actor_is_watchlist", 0)) if entry.get("actor_is_watchlist") is not None else 0,
            entry.get("event_type"),
            entry.get("event_at"),
            entry.get("observed_at"),
            entry.get("attribution_method"),
        ),
    )
    conn.commit()


def _sql_upsert_daily_snapshot(conn: sqlite3.Connection, snapshot: Dict[str, Any]) -> None:
    """Actualiza o inserta captura diaria."""
    conn.execute(
        """INSERT OR REPLACE INTO daily_snapshots
        (date, karma, posts_today, comments_today, recorded_at)
        VALUES (?, ?, ?, ?, ?)""",
        (
            snapshot.get("date"),
            snapshot.get("karma"),
            int(snapshot.get("posts_today", 0)) if snapshot.get("posts_today") is not None else 0,
            int(snapshot.get("comments_today", 0)) if snapshot.get("comments_today") is not None else 0,
            snapshot.get("recorded_at"),
        ),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# Persistencia JSONL (compatibilidad hacia abajo)
# ═══════════════════════════════════════════════════════════════

def _jsonl_write_entry(entry: Dict[str, Any]) -> None:
    """Append entry to JSONL file for backward compatibility."""
    try:
        JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger = __import__("logging").getLogger("services.karma_roi_tracker")
        logger.warning("No se pudo escribir JSONL: %s", e)


# ═══════════════════════════════════════════════════════════════
# Funciones públicas (mismas firmas que la versión JSONL anterior)
# ═══════════════════════════════════════════════════════════════

KARMA_TRACKER_FILE = str(JSONL_PATH)


def track_action(
    action_type: str,  # "post" o "comment"
    phase: str,  # "A" o "B"
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
    moltbook_id: str = None,
    model: str = "deepseek-v4-pro",
    thread_id: str = None,
    author: str = None,
    status: str = None,  # None = inferir de action_type (fix 2026-09-16)
    source: str = None,
) -> Dict[str, Any]:
    """Registra una acción (post/comment) en el tracker de karma ROI.
    
    Escribe en SQLite (data/karma_roi.db) y mantiene compatibilidad JSONL
    en data/karma_roi_tracker.jsonl para scripts existentes.
    
    Parámetros opcionales:
    - status: published | rejected | duplicate | failed (default: published)
    - source: own_post_reply | thread_followup | feed_reply (default: determina automáticamente)
    """
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    
    # Determinar comment_id y post_id según el tipo
    if action_type == "comment":
        comment_id = moltbook_id  # moltbook_id es el comment_id en este caso
        post_id = thread_id
        if not post_id:
            import logging
            logging.getLogger("services.karma_roi_tracker").warning(
                "track_action: post_id vacío para comment, usando comment_id como fallback"
            )
            post_id = comment_id  # fallback: usar el mismo comment_id como post_id
        parent_comment_id = thread_id  # para comments, thread_id es el padre
    else:
        comment_id = moltbook_id  # para posts, moltbook_id es el post_id
        # Fix 2026-09-16: post rechazado no tiene moltbook_id todavía.
        # El schema exige post_id NOT NULL. Fallback con ID sintético
        # para poder trackear el coste del intento sin violar el constraint.
        if moltbook_id:
            post_id = moltbook_id
        else:
            post_id = f"pending-post-{int(now.timestamp() * 1000)}"
            import logging
            logging.getLogger("services.karma_roi_tracker").warning(
                "track_action: post sin moltbook_id (rejected), post_id sintético=%s",
                post_id,
            )
        parent_comment_id = None
    
    # Determinar source
    # Lógica: si se especifica source, úsalo; si no, default a own_post_reply
    # para posts, y feed_reply para comments sin followup
    if source:
        used_source = source
    elif action_type == "comment" and thread_id and thread_id.startswith("followup_"):
        used_source = "thread_followup"
    else:
        used_source = "own_post_reply"  # default universal
    
    # Asegurar que source no sea None para la restricción NOT NULL de la BD
    used_source = used_source or "own_post_reply"
    
    # Fix 2026-09-16: inferir status del sufijo del action_type si no se
    # paso explicitamente. Evita que post_rejected/comment_rejected caigan
    # al default published y contaminen el tracking.
    if status is None:
        if action_type.endswith("_rejected"):
            status = "rejected"
        elif action_type.endswith("_duplicate"):
            status = "duplicate"
        elif action_type.endswith("_failed"):
            status = "failed"
        else:
            status = "published"

    # Entrada SQLite
    sqlite_entry = {
        "comment_id": comment_id,
        "post_id": post_id,
        "parent_comment_id": parent_comment_id,
        "target_author": author,
        "target_is_watchlist": 0,  # se establece llamando convenientemente
        "source": used_source,
        "score": None,
        "model": model,
        "tier": None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
        "created_at": created_at,
        "status": status if status in VALID_STATUSES else "published",
    }
    
    # Entrada JSONL (compatibilidad)
    jsonl_entry = {
        "type": action_type,
        "moltbook_id": moltbook_id,
        "generated_at": created_at,
        "phase": phase,
        "cost_usd": round(cost_usd, 6),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "model": model,
        "thread_id": thread_id,  # Para comments: ID del post padre
        "author": author,  # Autor del post/thread
        "upvotes_1h": 0,
        "upvotes_24h": 0,
        "comments_received": 0,
        "karma_score": 0,  # upvotes × 1.0
        "last_updated": created_at
    }
    
    # Guardar en SQLite
    try:
        conn = _get_conn()
        _sql_insert_comment_action(conn, sqlite_entry)
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger("services.karma_roi_tracker").warning(
            "SQL error insertando comment_action: %s", e
        )
    
    # Escribir JSONL para compatibilidad
    _jsonl_write_entry(jsonl_entry)
    
    # Retornar formato consistente con la versión anterior
    return {
        "type": action_type,
        "moltbook_id": moltbook_id,
        "generated_at": created_at,
        "phase": phase,
        "cost_usd": round(cost_usd, 6),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "model": model,
        "thread_id": thread_id,
        "author": author,
        "upvotes_1h": 0,
        "upvotes_24h": 0,
        "comments_received": 0,
        "karma_score": 0,
        "last_updated": created_at
    }


def update_karma(moltbook_id: str, upvotes: int, comments: int = 0) -> None:
    """Actualiza karma para una acción existente."""
    # Actualizar en JSONL (compatibilidad). Regla 33: bytes, no texto.
    try:
        if JSONL_PATH.exists():
            entries: List[Dict[str, Any]] = []
            raw_bytes = JSONL_PATH.read_bytes()
            for line in raw_bytes.split(b"\n"):
                if line.strip():
                    entries.append(json.loads(line.decode("utf-8")))

            updated = False
            for entry in entries:
                if entry.get("moltbook_id") == moltbook_id:
                    entry["upvotes_1h"] = upvotes
                    entry["upvotes_24h"] = upvotes
                    entry["comments_received"] = comments
                    entry["karma_score"] = upvotes
                    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
                    updated = True
                    break

            if updated:
                payload = b"".join(
                    (json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8")
                    for e in entries
                )
                JSONL_PATH.write_bytes(payload)
    except Exception as e:
        import logging
        logging.getLogger("services.karma_roi_tracker").warning(
            "Error actualizando JSONL karma: %s", e
    )
    
    # También actualizar en SQLite si existe
    try:
        conn = _get_conn()
        # Buscar entrada existente
        cursor = conn.execute(
            "SELECT comment_id FROM comment_actions WHERE comment_id = ?",
            (moltbook_id,),
        )
        row = cursor.fetchone()
        if row:
            conn.execute(
                """UPDATE comment_actions 
                   SET cost_usd = cost_usd, input_tokens = input_tokens, output_tokens = output_tokens,
                       score = ?, last_updated = ? 
                   WHERE comment_id = ?""",
                (upvotes, datetime.now(timezone.utc).isoformat(), moltbook_id),
            )
            conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger("services.karma_roi_tracker").warning(
            "SQL error actualizando comment_action: %s", e
        )


def get_roi_summary(hours: int = 24) -> Dict[str, Any]:
    """Calcula ROI comparativo Phase A vs Phase B usando SQLite como fuente principal."""
    conn = _get_conn()
    
    # Query comments published en la ventana de tiempo
    cutoff = (datetime.now(timezone.utc) ).timestamp() - (hours * 3600)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    
    # Comments por phase
    cursor = conn.execute(
        """SELECT cost_usd, status, source FROM comment_actions 
           WHERE created_at >= ?""",
        (cutoff_iso,),
    )
    rows = cursor.fetchall()
    
    # Phase A y Phase B las distinguimos por el campo source o por convenciones
    # Por ahora, Phase A = posts (own_post_reply), Phase B = comments
    phase_a_entries = []
    phase_b_entries = []
    
    for row in rows:
        cost, status, source = row
        # Phase A: posts (own_post_reply), Phase B: comments (feed_reply, thread_followup)
        if source == "own_post_reply":
            phase_a_entries.append({"cost_usd": cost, "status": status})
        else:
            phase_b_entries.append({"cost_usd": cost, "status": status})
    
    conn.close()
    
    # Calcular métricas (misma lógica que versión anterior pero usando SQLite data)
    def calc_metrics(actions: List[Dict]) -> Dict[str, Any]:
        if not actions:
            return {"count": 0, "total_cost": 0, "total_karma": 0, "karma_per_usd": 0, "avg_cost": 0}
        
        total_cost = sum(a.get("cost_usd", 0) for a in actions)
        # Karma = upvotes atribuibles; por ahora usamos cost como proxy
        # En implementación completa, se sumarían upvotes de engagement_events
        
        return {
            "count": len(actions),
            "total_cost": round(total_cost, 6),
            "total_karma": 0,  # Se calcularía desde engagement_events
            "karma_per_usd": round(0 / total_cost, 2) if total_cost > 0 else 0,
            "avg_cost": round(total_cost / len(actions), 6),
        }
    
    metrics_a = calc_metrics(phase_a_entries)
    metrics_b = calc_metrics(phase_b_entries)
    
    # ROI ratio
    roi_ratio = 0
    if metrics_b["karma_per_usd"] > 0 and metrics_a["karma_per_usd"] > 0:
        roi_ratio = round(metrics_a["karma_per_usd"] / metrics_b["karma_per_usd"], 2)
    elif metrics_b["karma_per_usd"] > 0:
        roi_ratio = float('inf')  # Phase A inefficiente comparada
    
    recommendation = ""
    if metrics_b["count"] < 10 and metrics_a["count"] < 10:
        recommendation = "Datos insuficientes: se requieren al menos 10 acciones en cada fase."
    elif (metrics_a["total_cost"] + metrics_b["total_cost"]) < 0.01:
        recommendation = "Datos insuficientes: aún no hay gasto observable suficiente para comparar eficiencia."
    elif roi_ratio > 2.0:
        recommendation = "Phase A es más de 2x eficiente: aumentar posts y reducir comentarios de bajo rendimiento."
    elif roi_ratio > 1.0:
        recommendation = "Phase A es más eficiente: mantener el balance, inclinándolo moderadamente hacia posts."
    elif roi_ratio >= 0.5:
        recommendation = "Phase B es más eficiente: concentrar comentarios en la watchlist y threads de alta señal."
    else:
        recommendation = "Phase B es más de 2x eficiente: reducir posts y limitar comentarios a oportunidades de alto valor."
    
    return {
        "period_hours": hours,
        "phase_a": metrics_a,
        "phase_b": metrics_b,
        "roi_ratio_a_vs_b": roi_ratio,
        "recommendation": recommendation,
    }


# ═══════════════════════════════════════════════════════════════
# Nuevas funciones para engagement y attribution (diseño secciones B y C)
# ═══════════════════════════════════════════════════════════════

def record_engagement(
    action_comment_id: str,
    action_post_id: str,
    actor: str,
    actor_is_watchlist: int,
    event_type: str,
    event_at: str,
    observed_at: str,
    attribution_method: str = "direct_comment",
) -> bool:
    """Registra un evento de engagement (upvote, reply, follow).
    
    Usa INSERT OR IGNORE para deduplicación por UNIQUE(action_comment_id, actor, event_type, event_at).
    Sólo registra si attribution_method es directo o ventana misma-post.
    Returns True si se insertó, False si fue ignorado (duplicado).
    """
    # Validar attribution_method
    if attribution_method not in VALID_ATTRIBUTION_METHODS:
        import logging
        logging.getLogger("services.karma_roi_tracker").warning(
            "attribution_method inválido: %s, usando direct_comment", attribution_method
        )
        attribution_method = "direct_comment"
    
    # Validar event_type
    if event_type not in VALID_EVENT_TYPES:
        import logging
        logging.getLogger("services.karma_roi_tracker").warning(
            "event_type inválido: %s, usando comment_reply", event_type
        )
        event_type = "comment_reply"
    
    conn = _get_conn()
    entry = {
        "action_comment_id": action_comment_id,
        "action_post_id": action_post_id,
        "actor": actor,
        "actor_is_watchlist": actor_is_watchlist,
        "event_type": event_type,
        "event_at": event_at,
        "observed_at": observed_at,
        "attribution_method": attribution_method,
    }
    
    try:
        _sql_insert_engagement_event(conn, entry)
        conn.close()
        return True
    except Exception as e:
        import logging
        logging.getLogger("services.karma_roi_tracker").error("Error registrando engagement: %s", e)
        conn.close()
        return False


def record_daily_snapshot(date: str, posts_today: int = 0, comments_today: int = 0, karma: int = None) -> None:
    """Registra una captura diaria de métricas."""
    snapshot = {
        "date": date,
        "karma": karma,
        "posts_today": posts_today,
        "comments_today": comments_today,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        conn = _get_conn()
        _sql_upsert_daily_snapshot(conn, snapshot)
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger("services.karma_roi_tracker").warning("Error registrando snapshot diario: %s", e)


# ════════════════════════════════════════════════════════════════
# NUEVA FUNCTION: record_phase_b_comment
# Registra una acción de comentario en Phase B con metadatos completos.
# - Valida source contra los 3 valores permitidos.
# - Usa tier/provider real desde la metadata de ModelCascade.
# - Es idempotente por comment_id (INSERT OR REPLACE).
# - No lanza excepción que detenga Phase B (catch-all).
# - Separa costes propios de follow-ups vs feed vs own_post.
# ═══════════════════════════════════════════════════════════════
def record_phase_b_comment(
    comment_id: str,
    post_id: str,
    parent_comment_id: Optional[str],
    source: str,
    target_author: Optional[str],
    target_is_watchlist: int,
    score: Optional[float],
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    status: str,
) -> bool:
    """Registra una acción de comentario en Phase B.

    Parametros (mismo esquema que track_action pero enfocado en Phase B):
    - comment_id: ID único devuelto por Moltbook API (obligatorio).
    - post_id: ID del post donde se publicó.
    - parent_comment_id: ID del comentario padre (None si es top-level).
    - source: debe ser one-of {own_post_reply, thread_followup, feed_reply}.
    - target_author: autor objetivo (puede ser None).
    - target_is_watchlist: 1 si es watchlist, 0 otro caso.
    - score: score de calidad (puede ser None).
    - model: nombre del modelo usado.
    - tier: tier/provider real (p.ej. tier_pro, tier_fallback, openrouter).
    - input_tokens: tokens de entrada consumidos.
    - output_tokens: tokens de salida consumidos.
    - cost_usd: costo USD. 0.0 está permitido si desconocido (cost_status="unknown").
    - status: published | rejected | duplicate | failed.

    Returns True si el registro tuvo éxito, False en caso de error (nunca lanza excepción).
    """
    # ---- Validaciones defensivas ----
    try:
        # Validar source
        valid_sources = ("own_post_reply", "thread_followup", "feed_reply")
        if source not in valid_sources:
            import logging
            logging.getLogger("services.karma_roi_tracker").warning(
                "record_phase_b_comment: source inválido=%s, usando 'own_post_reply'", source
            )
            source = "own_post_reply"

        # Validar status
        if status not in VALID_STATUSES:
            import logging
            logging.getLogger("services.karma_roi_tracker").warning(
                "record_phase_b_comment: status inválido=%s, usando 'published'", status
            )
            status = "published"

        # Asegurar tipos seguros
        comment_id = str(comment_id) if comment_id else ""
        post_id = str(post_id) if post_id else ""
        if not comment_id:
            import logging
            logging.getLogger("services.karma_roi_tracker").error(
                "record_phase_b_comment: comment_id vacío, abortando"
            )
            return False

        # Normalizar target_is_watchlist a entero
        watchlist_int = int(target_is_watchlist) if target_is_watchlist is not None else 0

        # Normalizar score a float o None
        score_val = float(score) if score is not None else None

        # Normalizar cost_usd a float
        cost_val = float(cost_usd) if cost_usd is not None else 0.0

        # Usar values seguros para la inserción
        safe_model = str(model) if model else "unknown"
        safe_tier = str(tier) if tier else "unknown"

        now = datetime.now(timezone.utc)
        created_at = now.isoformat()

        # INSERT OR REPLACE para idempotencia por comment_id
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO comment_actions
                (comment_id, post_id, parent_comment_id, target_author, target_is_watchlist,
                 source, score, model, tier, input_tokens, output_tokens, cost_usd,
                 created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comment_id,
                    post_id,
                    parent_comment_id,
                    target_author,
                    watchlist_int,
                    source,
                    score_val,
                    safe_model,
                    safe_tier,
                    int(input_tokens) if input_tokens is not None else 0,
                    int(output_tokens) if output_tokens is not None else 0,
                    round(cost_val, 6),
                    created_at,
                    status,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            import logging
            logging.getLogger("services.karma_roi_tracker").error(
                "SQL error INSERT en record_phase_b_comment comment_id=%s: %s", comment_id, e
            )
            try:
                conn.close()
            except Exception:
                pass
            return False

        # Escribir JSONL para compatibilidad hacia atrás (best-effort)
        try:
            jsonl_entry = {
                "type": "comment",
                "moltbook_id": comment_id,
                "generated_at": created_at,
                "phase": "B",
                "cost_usd": round(cost_val, 6),
                "input_tokens": int(input_tokens) if input_tokens is not None else 0,
                "output_tokens": int(output_tokens) if output_tokens is not None else 0,
                "total_tokens": (int(input_tokens) if input_tokens is not None else 0)
                + (int(output_tokens) if output_tokens is not None else 0),
                "model": safe_model,
                "thread_id": post_id,
                "author": target_author,
                "upvotes_1h": 0,
                "upvotes_24h": 0,
                "comments_received": 0,
                "karma_score": int(score_val) if score_val is not None else 0,
                "last_updated": created_at,
                "source": source,
                "tier": safe_tier,
            }
            _jsonl_write_entry(jsonl_entry)
        except Exception:
            pass  # JSONL failure no detiene Phase B

        # Log estructurado de éxito
        import logging
        logger = logging.getLogger("services.karma_roi_tracker")
        logger.info(
            "karma_roi_comment_recorded comment_id=%s source=%s tier=%s cost_usd=%.6f status=%s",
            comment_id, source, safe_tier, cost_val, status,
        )
        return True

    except Exception as e:
        # Last resort: never let an exception escape this function
        import logging
        logging.getLogger("services.karma_roi_tracker").critical(
            "Unexpected error in record_phase_b_comment: %s", e,
            exc_info=True,
        )
        return False


# ═══════════════════════════════════════════════════════════════
# Función de ayuda para compatibilidad: KARMA_TRACKER_FILE aún apunta a JSONL
# ═══════════════════════════════════════════════════════════════

# NOTE: KARMA_TRACKER_FILE mantiene la ruta JSONL para scripts existentes.
# El tracker usa SQLite como fuente de verdad; el JSONL se mantiene por compatibilidad.
# Scripts que lean data/karma_roi_tracker.jsonl aún funcionarán, pero la fuente de verdad
# es data/karma_roi.db. Migre gradualmente a las nuevas funciones SQL.


# ════════════════════════════════════════════════════════════════
__all__ = [
    "track_action",
    "update_karma", 
    "get_roi_summary",
    "record_engagement",
    "record_daily_snapshot",
    "record_phase_b_comment",
    "KARMA_TRACKER_FILE",
    "DB_PATH",
]
