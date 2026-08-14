# -*- coding: utf-8 -*-
"""
Comment votes ledger: retorno real (upvotes) por comentario publicado.

Cierra el circulo post -> comentario -> upvote: el karma global no descompone
de donde vienen los votos. Este ledger guarda, por cada comentario propio
publicado, su research_value_score (el que uso la cola) y los upvotes que
recibio en la plataforma. Con eso se puede ver si la calidad medida
(dual_scoring) correlaciona con el retorno real (upvotes) — la metrica externa
que faltaba.

Storage: data/comment_votes.jsonl
  {"comment_id": "...", "post_id": "...", "date": "YYYY-MM-DD",
   "value_score": 0.3, "upvotes": 2, "checked_at": iso}
El refresh actualiza upvotes en el mismo archivo (upsert por comment_id).
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.comment_votes")

_VOTES_PATH = Path("data/comment_votes.jsonl")


def _load(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    path = path or _VOTES_PATH
    if not path.exists():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("comment_id"):
                out[str(rec["comment_id"])] = rec
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("comment_votes: no se pudo leer %s: %s", path, e)
    return out


def _save(records: Dict[str, Dict[str, Any]], path: Optional[Path] = None) -> None:
    path = path or _VOTES_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for rec in records.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("comment_votes: no se pudo escribir %s: %s", path, e)


def record_published_comment(post_id: str, comment_id: str, value_score: float,
                             reason: str = "", path: Optional[Path] = None) -> bool:
    """Registra un comentario propio publicado con su score de valor y el
    motivo por el que entro a la cola (watchlist/historial/primera_interaccion/
    valor). Con eso se mide QUE canal produce retorno y cual es ruido."""
    if not comment_id:
        return False
    records = _load(path)
    key = str(comment_id)
    if key in records:
        return False
    records[key] = {
        "comment_id": key,
        "post_id": str(post_id or ""),
        "date": datetime.now(timezone.utc).date().isoformat(),
        "value_score": round(float(value_score or 0.0), 3),
        "reason": reason or "valor",
        "upvotes": None,
        "checked_at": None,
    }
    _save(records, path)
    return True


def refresh_comment_votes(api: Any, post_id: str, comment_ids: List[str],
                          path: Optional[Path] = None, max_pages: int = 6) -> int:
    """Actualiza los upvotes de nuestros comentarios en UN post.

    Fetch paginado (offset por 50) con deteccion defensiva: si la API ignora
    el offset (vuelve la misma primera pagina), se corta. Actualiza solo los
    comment_id registrados en el ledger y loguea cuantos no se localizaron
    (nuestros comentarios pueden quedar fuera de las primeras 50 top-level
    en posts con cientos de comentarios). Devuelve cuantos se actualizaron."""
    ids = [str(c) for c in comment_ids if c]
    if not ids:
        return 0
    records = _load(path)
    wanted = {i for i in ids if i in records}
    if not wanted:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    found: set = set()
    prev_ids: Optional[set] = None
    for page in range(max_pages):
        try:
            comments = api.fetch_post_comments(post_id, offset=page * 50) or []
        except TypeError:
            # cliente sin soporte de offset: una sola pagina
            comments = api.fetch_post_comments(post_id) or []
        if not comments:
            break
        current_ids = {str(c.get("id") or c.get("comment_id")) for c in comments}
        if page > 0 and prev_ids is not None and current_ids == prev_ids:
            break  # la API ignora el offset: no hay mas paginas
        prev_ids = current_ids
        for c in comments:
            cid = c.get("id") or c.get("comment_id")
            if cid and str(cid) in wanted:
                rec = records[str(cid)]
                rec["upvotes"] = int(c.get("upvotes") or 0)
                rec["checked_at"] = now
                found.add(str(cid))
                updated += 1
        if not (wanted - found):
            break
    missing = wanted - found
    if missing:
        logger.warning(
            "comment_votes: %d de %d sin localizar en post %s (fuera de la ventana de fetch)",
            len(missing), len(wanted), post_id,
        )
    if updated:
        _save(records, path)
    return updated


def refresh_all_comment_votes(api: Any, agent_comment_ids: Dict[str, List[str]],
                              max_posts: int = 20, path: Optional[Path] = None) -> Dict[str, int]:
    """Actualiza los upvotes de nuestros comentarios registrados en el ledger.

    Prioriza los posts que tienen comentarios en el ledger (no los primeros N
    del dedup store, que pueden ser posts viejos sin entradas). Devuelve
    {posts, updated}."""
    records = _load(path)
    by_post: Dict[str, List[str]] = {}
    for cid, rec in records.items():
        pid = str(rec.get("post_id") or "")
        if pid:
            by_post.setdefault(pid, []).append(str(cid))
    if not by_post:
        return {"posts": 0, "updated": 0}
    updated = 0
    for pid, cids in list(by_post.items())[:max_posts]:
        updated += refresh_comment_votes(api, pid, cids, path=path)
    return {"posts": min(len(by_post), max_posts), "updated": updated}


def votes_summary(path: Optional[Path] = None) -> Dict[str, Any]:
    """Resumen del ledger: retorno por comentario, agrupado por rango de score."""
    records = list(_load(path).values())
    if not records:
        return {"total": 0, "with_votes": 0, "total_upvotes": 0, "by_score": {}}
    checked = [r for r in records if r.get("upvotes") is not None]
    total_upvotes = sum(int(r.get("upvotes") or 0) for r in checked)
    by_score: Dict[str, Dict[str, Any]] = {}
    for r in checked:
        s = float(r.get("value_score") or 0.0)
        bucket = "<=0.3" if s <= 0.3 else "0.31-0.5" if s <= 0.5 else "0.51-0.7" if s <= 0.7 else ">0.7"
        b = by_score.setdefault(bucket, {"n": 0, "upvotes": 0})
        b["n"] += 1
        b["upvotes"] += int(r.get("upvotes") or 0)
    return {
        "total": len(records),
        "with_votes": len(checked),
        "total_upvotes": total_upvotes,
        "by_score": by_score,
    }
