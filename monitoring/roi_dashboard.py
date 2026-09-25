# monitoring/roi_dashboard.py
"""Panel de lectura-only de métricas Karma ROI.

Fuente de verdad: data/karma_roi.db (SQLite).
No depende de paquetes externos; usa sqlite3, argparse, json, datetime, pathlib.

Ejemplos:
    python .\\monitoring\\roi_dashboard.py
    python .\\monitoring\\roi_dashboard.py --days 7
    python .\\monitoring\\roi_dashboard.py --format json
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path("data/karma_roi.db")


# ── Helpers internos ────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _query(sql: str, params: tuple = None) -> list:
    conn = _conn()
    try:
        if params:
            cur = conn.execute(sql, params)
        else:
            cur = conn.execute(sql)
        rows = cur.fetchall()
        return rows
    finally:
        conn.close()


# ── Métricas por ventana de tiempo ─────────────────────────────

def _rows_since(hours: int) -> list:
    """Devuelve rows de comment_actions en las últimas *hours* horas."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    # Fix P-092: este panel mide comentarios. Excluye posts Phase A
    # (action_type in {post, post_rejected}) que inflaban rechazados y costos.
    return _query(
        "SELECT * FROM comment_actions WHERE created_at >= ? AND action_type = \'comment\'",
        (cutoff_iso,),
    )


# ── Cálculo de métricas ────────────────────────────────────────

def _count_by_status(rows: list) -> dict:
    counts = {"published": 0, "rejected": 0, "duplicate": 0, "failed": 0}
    for r in rows:
        s = r["status"] if r["status"] in {"published", "rejected", "duplicate", "failed"} else "other"
        counts[s] += 1
    return counts


def _count_by_source(rows: list) -> dict:
    counts = {"own_post_reply": 0, "thread_followup": 0, "feed_reply": 0}
    for r in rows:
        s = r["source"] if r["source"] in counts else "other"
        counts[s] += 1
    return counts


def _engagement_counts(hours: int) -> dict:
    """Cuenta eventos de engagement en la ventana de *hours* horas."""
    sql = (
        "SELECT event_type, attribution_method, actor_is_watchlist "
        "FROM engagement_events "
        "WHERE event_at >= ?"
    )
    cutoff_str = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = _query(sql, (cutoff_str,))
    c = {"upvotes": 0, "replies": 0, "follows": 0, "watchlist_attributable": 0, "watchlist_non_attributable": 0}
    for r in rows:
        et = r["event_type"]
        am = r["attribution_method"]
        ai = r["actor_is_watchlist"]
        if et == "upvote":
            c["upvotes"] += 1
        elif et == "reply":
            c["replies"] += 1
        elif et == "follow":
            c["follows"] += 1
        if am in ("direct_comment", "same_post_window"):
            if ai:
                c["watchlist_attributable"] += 1
            else:
                c["watchlist_non_attributable"] += 1
    return c


# ── API pública ─────────────────────────────────────────────────

def get_metrics(days: int = 1) -> dict:
    """Retorna diccionario con métricas para ventana de *days* días."""
    rows = _rows_since(days * 24)
    stats = _count_by_status(rows)
    stats_source = _count_by_source(rows)
    eng = _engagement_counts(days * 24)
    total_cost = sum((r["cost_usd"] or 0) for r in rows if r["cost_usd"] is not None)

    published = stats["published"]
    rejected = stats["rejected"]
    duplicate = stats["duplicate"]
    failed = stats["failed"]
    total = published + rejected + duplicate + failed

    # Costes: publicados vs no productivos (rejected + duplicate + failed)
    published_cost = sum((r["cost_usd"] or 0) for r in rows if r["status"] == "published")
    nonproductive_cost = total_cost - published_cost

    # Upvotes / respuestas / follows
    upvotes = eng["upvotes"]
    replies = eng["replies"]
    follows = eng["follows"]

    # ROI: interacciones atribuibles / coste total
    if total_cost > 0:
        roi_observado = upvotes / total_cost
    else:
        roi_observado = 0.0

    # Tasa de publicación
    if total > 0:
        tasa_publicacion = published / total
    else:
        tasa_publicacion = 0.0

    # Costes marginales
    costo_por_upvote = total_cost / upvotes if upvotes > 0 else 0.0
    costo_por_respuesta = total_cost / replies if replies > 0 else 0.0
    costo_por_interaccion = total_cost / (upvotes + replies + follows) if (upvotes + replies + follows) > 0 else 0.0

    # Métricas por source
    source_metrics = {}
    for src in ["own_post_reply", "thread_followup", "feed_reply"]:
        src_rows = [r for r in rows if r["source"] == src]
        src_cost = sum((r["cost_usd"] or 0) for r in src_rows)
        src_published = sum(1 for r in src_rows if r["status"] == "published")
        source_metrics[src] = {
            "count": len(src_rows),
            "published": src_published,
            "cost": round(src_cost, 6),
        }

    # Métricas por watchlist
    watchlist_rows = [r for r in rows if r["target_is_watchlist"] == 1]
    watchlist_cost = sum((r["cost_usd"] or 0) for r in watchlist_rows)
    watchlist_published = sum(1 for r in watchlist_rows if r["status"] == "published")

    return {
        "period_days": days,
        "comentarios_publicados": published,
        "comentarios_rechazados": rejected,
        "comentarios_duplicados": duplicate,
        "comentarios_fallidos": failed,
        "comentarios_total": total,
        "costo_publicado": round(published_cost, 6),
        "costo_no_productivo": round(nonproductive_cost, 6),
        "costo_total": round(total_cost, 6),
        "upvotes_atribuibles": upvotes,
        "respuestas_atribuibles": replies,
        "follows_atribuibles": follows,
        "interacciones_watchlist_atribuibles": eng["watchlist_attributable"],
        "interacciones_watchlist_no_atribuibles": eng["watchlist_non_attributable"],
        "costo_por_upvote": round(costo_por_upvote, 6),
        "costo_por_respuesta": round(costo_por_respuesta, 6),
        "costo_por_interaccion_atribuible": round(costo_por_interaccion, 6),
        "roi_observado": round(roi_observado, 6),
        "tasa_publicacion": round(tasa_publicacion, 4),
        "metricas_por_source": source_metrics,
        "metricas_watchlist": {
            "publicados": watchlist_published,
            "costo": round(watchlist_cost, 6),
        },
    }


# ── CLI ──────────────────────────────────────────────────────────

def _main() -> int:
    parser = argparse.ArgumentParser(description="Karma ROI Dashboard (solo lectura)")
    parser.add_argument("--days", type=int, default=1, help="Ventana de días (1, 7, 30)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Formato de salida")
    args = parser.parse_args()

    data = get_metrics(args.days)

    if args.format == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    # Formato texto (predeterminado)
    if data.get("error"):
        print(f"❌ {data['error']}")
        return 0

    p = data
    print("\n" + "=" * 60)
    print(f"📊 KARMA ROI DASHBOARD - {p['period_days']}d")
    print("=" * 60)

    print("\n📝 Comentarios")
    print(f"   Publicados:   {p['comentarios_publicados']}")
    print(f"   Rechazados:   {p['comentarios_rechazados']}")
    print(f"   Duplicados:   {p['comentarios_duplicados']}")
    print(f"   Fallidos:     {p['comentarios_fallidos']}")
    print(f"   Total:        {p['comentarios_total']}")
    print(f"   Tasa publicación: {p['tasa_publicacion']:.1%}")

    print(f"\n💰 Costes")
    print(f"   Coste publicado:      ${p['costo_publicado']:.6f} USD")
    print(f"   Coste no productivo:  ${p['costo_no_productivo']:.6f} USD")
    print(f"   Coste total:          ${p['costo_total']:.6f} USD")

    print(f"\n⚡ Interacciones")
    print(f"   Upvotes atribuibles:      {p['upvotes_atribuibles']}")
    print(f"   Respuestas atribuibles:   {p['respuestas_atribuibles']}")
    print(f"   Follows atribuibles:      {p['follows_atribuibles']}")
    print(f"   Watchlist attributable:   {p['interacciones_watchlist_atribuibles']}")
    print(f"   Watchlist non-attributable: {p['interacciones_watchlist_no_atribuibles']}")

    print(f"\n💵 Costes marginales")
    print(f"   Costo por upvote:       ${p['costo_por_upvote']:.6f} USD")
    print(f"   Costo por respuesta:    ${p['costo_por_respuesta']:.6f} USD")
    print(f"   Costo por interacción:  ${p['costo_por_interaccion_atribuible']:.6f} USD")

    print(f"\n📈 ROI")
    print(f"   ROI observado (interacciones/coste): {p['roi_observado']:.4f}")
    print("\n" + "=" * 60 + "\n")

    return 0


# ── Punto de entrada ────────────────────────────────────────────

if __name__ == "__main__":
    try:
        exit_code = _main()
        raise SystemExit(exit_code)
    except Exception as e:
        print(f"❌ Error: {e}")
        import sys
        sys.exit(1)