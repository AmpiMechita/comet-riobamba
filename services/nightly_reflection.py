# -*- coding: utf-8 -*-
"""Reflexion diaria: acumula las interacciones del dia en conocimiento durable.

Cierra el loop observacion -> conocimiento -> publicacion:

  1. Observacion: el dia genera eventos reales -> data/value_log.jsonl
     (tema, tipo de problema, resumen problema/solucion) + retorno real en
     data/comment_votes.jsonl (upvotes) + inbound de watchlist.
  2. Conocimiento: esta reflexion destila esos eventos en topics nuevos para
     la agenda de investigacion (source="nightly_reflection") y en terminos
     nuevos. Fase A los recoge al dia siguiente como material editorial
     anclado a interacciones reales, no a opiniones.
  3. Publicacion: Phase A publica el post.

Anti-fabricacion: los topics se construyen SOLO con texto real de los eventos
(tema + resumen de problema). Nunca se inventa un mecanismo ni una war-story:
"Invent the mechanism, never the evidence".

Guardrails:
  - Cadencia minima (REFLECT_INTERVAL_HOURS, default 18h): no refractar si el
    ultimo run es reciente. Persistida en data/nightly_reflection_state.json.
  - Senal minima: solo eventos con clasificacion de valor real y con resumen
    de problema no vacio. El retorno (upvotes) solo etiqueta priority, no
    fabrica nada.
  - Tope por corrida (REFLECT_MAX_TOPICS) para no inundar la agenda.
  - Dedupe por tema exacto dentro de la corrida (la agenda ya dedupe topics).

Uso: python -m services.nightly_reflection [--force]
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.nightly_reflection")

# ── Rutas (sobrescribibles en tests via parametros path=...) ───────
VALUE_LOG_PATH = Path("data/value_log.jsonl")
VOTES_PATH = Path("data/comment_votes.jsonl")
INBOUND_PATH = Path("data/watchlist_inbound_today.json")
STATE_PATH = Path("data/nightly_reflection_state.json")

# ── Guardrails ─────────────────────────────────────────────────────
RUN_INTERVAL_HOURS = float(os.getenv("REFLECT_INTERVAL_HOURS", "18"))
MAX_TOPICS_PER_RUN = int(os.getenv("REFLECT_MAX_TOPICS", "3"))
MAX_TERMS_PER_RUN = int(os.getenv("REFLECT_MAX_TERMS", "5"))
LOOKBACK_HOURS = float(os.getenv("REFLECT_LOOKBACK_HOURS", "36"))

# Clasificaciones de valor que cuentan como senal real.
_VALID_CLASSIFICATIONS = {"resolvio_problema", "aporte_util"}

# Temas genericos que no aportan como topic (ruido).
_BAN_TOPICS_LOWERCASE = {
    "hola", "hello", "gracias", "thanks", "new thread", "off topic",
}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except OSError as e:
        logger.warning("nightly_reflection: no se pudo leer %s: %s", path, e)
    return out


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_events(cutoff: datetime, events_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Eventos de valor con senal (clasificacion util) desde cutoff."""
    path = events_path or VALUE_LOG_PATH
    out: List[Dict[str, Any]] = []
    for ev in _read_jsonl(path):
        ev_ts = _parse_dt(ev.get("timestamp") or "")
        if ev_ts is None or ev_ts < cutoff:
            continue
        if (ev.get("clasificacion_valor") or "") not in _VALID_CLASSIFICATIONS:
            continue
        if not str(ev.get("resumen_problema") or "").strip():
            continue
        out.append(ev)
    return out


def load_mark_votes(min_upvotes: int = 1, votes_path: Optional[Path] = None) -> Dict[str, int]:
    """comment_id -> upvotes de los comentarios con retorno real."""
    path = votes_path or VOTES_PATH
    out: Dict[str, int] = {}
    for rec in _read_jsonl(path):
        try:
            up = int(rec.get("upvotes") or 0)
        except (TypeError, ValueError):
            continue
        cid = str(rec.get("comment_id") or "")
        if cid and up >= min_upvotes:
            out[cid] = up
    return out


def _tema_key(topic: str) -> str:
    return " ".join((topic or "").lower().split())


def build_topics(events: List[Dict[str, Any]],
                 votes_by_comment: Dict[str, int],
                 max_topics: int = MAX_TOPICS_PER_RUN) -> List[Dict[str, Any]]:
    """Destila hasta max_topics candidatos.

    Un topic = tema + resumen de problema (texto real del evento). Prioriza
    los que tienen retorno real (upvotes > 0). No duplica temas en el run."""
    scored: List[Dict[str, Any]] = []
    seen: set = set()
    for ev in events:
        tema = (ev.get("tema") or "").strip()
        problema = (ev.get("resumen_problema") or "").strip()
        if not tema or not problema:
            continue
        if _tema_key(tema) in _BAN_TOPICS_LOWERCASE:
            continue
        if _tema_key(problema)[:20] in _BAN_TOPICS_LOWERCASE:
            continue
        cid = str(ev.get("comment_id") or "")
        upvotes = int(votes_by_comment.get(cid, 0))
        key = _tema_key(tema)
        if key in seen:
            continue
        seen.add(key)

        topic = f"{tema}: {problema[:220]}".strip()
        if len(topic) < 2:
            continue
        tags = ["nightly_reflection", str(ev.get("tipo_problema") or "insight")]
        if upvotes > 0:
            tags.append(f"retorno_real_{upvotes}")
        scored.append({"topic": topic, "proposal": problema,
                       "source": "nightly_reflection",
                       "tags": tags, "upvotes": upvotes})
    scored.sort(key=lambda t: -t["upvotes"])
    return scored[:max_topics]


def build_terms(events: List[Dict[str, Any]], max_terms: int = MAX_TERMS_PER_RUN) -> List[Dict[str, Any]]:
    """Terminos observados (temas de eventos) para la agenda."""
    terms: List[Dict[str, Any]] = []
    seen: set = set()
    for ev in events:
        raw = (ev.get("tema") or "").strip()
        key = _tema_key(raw)
        if not key or key in _BAN_TOPICS_LOWERCASE or key in seen:
            continue
        seen.add(key)
        terms.append({"term": raw, "context": "generated-observations",
                      "source": "nightly_reflection"})
        if len(terms) >= max_terms:
            break
    return terms


def should_run(state: Dict[str, Any], now=None) -> bool:
    """True si gana la cadencia (>= RUN_INTERVAL_HOURS) o nunca corrio."""
    if not state or not state.get("last_run"):
        return True
    now = now or datetime.now(timezone.utc)
    last = _parse_dt(str(state["last_run"]))
    if last is None:
        return True
    return (now - last).total_seconds() >= RUN_INTERVAL_HOURS * 3600


def run_reflection(*, force: bool = False, state_path: Optional[Path] = None,
                   events_path: Optional[Path] = None, votes_path: Optional[Path] = None,
                   inbound_path: Optional[Path] = None, agenda=None,
                   now=None) -> Dict[str, Any]:
    """Ejecuta la reflexion (si cadencia vencida o force). Devuelve resumen."""
    target_state = state_path if state_path else STATE_PATH
    state = _read_json(target_state)
    if not force and not should_run(state, now=now):
        return {"ran": False, "reason": "cadence_not_due",
                "topics_added": 0, "terms_added": 0}

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    events = load_events(cutoff, events_path=events_path)
    votes = load_mark_votes(min_upvotes=1, votes_path=votes_path)

    from services.research_agenda import load_agenda, save_agenda
    ag = agenda if agenda is not None else load_agenda()

    topics = build_topics(events, votes)
    added = 0
    for t in topics:
        ag.add_topic(t["topic"], source=t["source"], tags=t["tags"])
        added += 1

    terms = build_terms(events)
    for term in terms:
        ag.add_new_term(term["term"], context=term["context"], source=term["source"])

    if agenda is None:
        save_agenda(ag)

    new_state = {"last_run": now.isoformat(),
                 "topics_added": added, "terms_added": len(terms),
                 "events_seen": len(events)}
    try:
        target_state.parent.mkdir(parents=True, exist_ok=True)
        target_state.write_text(json.dumps(new_state, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except OSError as e:
        logger.warning("nightly_reflection: no se pudo escribir estado %s: %s", target_state, e)

    return {"ran": True, "events_seen": len(events), "topics_added": added,
            "terms_added": len(terms), "topics": [t["topic"] for t in topics]}


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass
    force = "--force" in argv
    res = run_reflection(force=force)
    if not res.get("ran"):
        print("reflexion: cadencia no vencida (usa --force)")
        return 0
    print(f"reflexion: {res.get('events_seen', 0)} eventos, "
          f"{res.get('topics_added', 0)} topics, {res.get('terms_added', 0)} terminos.")
    for t in res.get("topics", []):
        print(f"  -> {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())