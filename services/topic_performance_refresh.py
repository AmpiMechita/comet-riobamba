# -*- coding: utf-8 -*-
"""
Topic Performance Refresh

Logica extraida de scripts/refresh_topic_performance.py para poder correrla
tanto manual (script CLI, sin ventana) como automatica (Fase C, con guard de
frecuencia y ventana de 14 dias).

data/topic_performance.jsonl es lo que Fase A lee via _load_topic_performance()
para filtrar temas con engagement cero comprobado — sin refresh automatico, el
agente ve datos congelados desde la ultima corrida manual.

La ventana (window_days) existe porque topic_performance.jsonl no tiene prune:
sin limite, el costo por corrida automatica (1 GET + 0.6s por post) crece sin
tope con la vida del agente. El script manual usa window_days=None (refresca
todo, comportamiento historico).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

DATA_PATH = Path("data/topic_performance.jsonl")

# ── Frequency guard (mismo patron que arxiv_topic_source.py) ──────────
REFRESH_STATE_PATH = Path("data/topic_performance_refresh_last_run.json")
REFRESH_INTERVAL_HOURS = float(os.getenv("TOPIC_PERFORMANCE_REFRESH_INTERVAL_HOURS", "24"))


def _load_refresh_last_run() -> float:
    try:
        with open(REFRESH_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return float(data.get("last_refreshed_at", 0.0))
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    except Exception as e:
        logger.debug("topic_performance_refresh: could not read refresh state: %s", e)
        return 0.0


def _save_refresh_last_run(epoch: float) -> None:
    try:
        REFRESH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REFRESH_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_refreshed_at": epoch}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("topic_performance_refresh: could not persist refresh state: %s", e)


def _parse_published_at(raw: str) -> Optional[datetime]:
    """Parsea published_at tolerando el sufijo 'Z' y timestamps naive (se asumen UTC)."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def refresh_topic_performance(
    window_days: Optional[int] = 14,
    client: Any = None,
    sleep_seconds: float = 0.6,
) -> Dict[str, Any]:
    """Refresca score/comment_count de topic_performance.jsonl contra la API.

    window_days=None refresca TODOS los registros (uso manual, comportamiento
    historico del script); un entero limita el refresh a posts publicados
    dentro de esa ventana (uso automatico en Fase C). Los registros fuera de
    ventana se preservan tal cual, sin llamar a la API.

    Solo hace GETs (read-only sobre Moltbook); escribe backup con timestamp
    del jsonl antes de tocarlo.
    """
    if not DATA_PATH.exists():
        logger.info("topic_performance_refresh: %s no existe, nada que refrescar.", DATA_PATH)
        return {"records": 0, "checked": 0, "failed": 0, "skipped_window": 0, "backup": None}

    if client is None:
        from services.moltbook_api_client import MoltbookAPIClient
        client = MoltbookAPIClient()

    original = DATA_PATH.read_text(encoding="utf-8")

    # ── Backup con timestamp antes de escribir ────────────────────────
    backup_path = DATA_PATH.with_suffix(
        f".jsonl.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup_path.write_text(original, encoding="utf-8")

    records = [json.loads(line) for line in original.splitlines() if line.strip()]

    cutoff: Optional[datetime] = None
    if window_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    checked = 0
    failed = 0
    skipped_window = 0

    for i, rec in enumerate(records):
        post_id = (rec.get("post_id") or "").strip()
        if not post_id or not UUID_RE.match(post_id) or "dry-run" in post_id.lower():
            continue

        if cutoff is not None:
            published = _parse_published_at(rec.get("published_at") or "")
            if published is None or published < cutoff:
                skipped_window += 1
                continue

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        post = client.get_post(post_id)
        if post is None:
            failed += 1
            continue

        rec["score"] = post.get("score") or post.get("upvotes") or 0
        rec["comment_count"] = post.get("comment_count", 0)
        rec["score_checked"] = True
        rec["checked_at"] = datetime.now(timezone.utc).isoformat()
        checked += 1

        if (i + 1) % 25 == 0:
            logger.info(
                "topic_performance_refresh: ... %d/%d checked=%d failed=%d",
                i + 1, len(records), checked, failed,
            )

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(
        "topic_performance_refresh: records=%d checked=%d failed=%d skipped_window=%d",
        len(records), checked, failed, skipped_window,
    )
    return {
        "records": len(records),
        "checked": checked,
        "failed": failed,
        "skipped_window": skipped_window,
        "backup": str(backup_path),
    }


def refresh_topic_performance_guarded(
    window_days: Optional[int] = 14,
    client: Any = None,
    respect_interval: bool = True,
    interval_hours: float = REFRESH_INTERVAL_HOURS,
) -> Dict[str, Any]:
    """Wrapper con guard de frecuencia para uso en ciclos automaticos (Fase C).

    Seguro de llamar en cada ciclo: si no paso ``interval_hours`` desde la
    ultima corrida exitosa, no-opea en silencio (mismo patron que
    refresh_agenda_from_arxiv_guarded). Pasar respect_interval=False para
    forzar (tests / manual).

    Returns: {"skipped": bool, **resultado de refresh_topic_performance}
    """
    if respect_interval:
        last_run = _load_refresh_last_run()
        if last_run > 0.0:
            elapsed_hours = (time.time() - last_run) / 3600.0
            if elapsed_hours < interval_hours:
                logger.debug(
                    "topic_performance_refresh: skipped (%.1fh since last run < %.1fh interval)",
                    elapsed_hours, interval_hours,
                )
                return {"skipped": True, "checked": 0}

    result = refresh_topic_performance(window_days=window_days, client=client)
    _save_refresh_last_run(time.time())
    return {"skipped": False, **result}
