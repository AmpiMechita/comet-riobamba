# -*- coding: utf-8 -*-
"""
Incident store: incidentes REALES y verificables del propio proyecto.

Cada entrada en data/incidents.jsonl es un fallo diagnosticado con numeros
verificables (git log, logs, telemetria). Es la fuente de la prioridad alta
'own_incident' de Phase A: ningun otro agente puede escribir estos posts
porque no vivio estos fallos.

Reglas de contenido (curacion humana, no automatizable):
- SOLO el patron tecnico y los numeros reales. Nada de rutas internas,
  nombres de archivo del repo, claves, ni detalles que identifiquen
  infraestructura privada.
- 'used': True cuando el post se PUBLICO (marcado en Phase A). Un incidente
  usado no se re-registra en la agenda, asi que no se repite.
"""

import json
import logging
import re
from typing import Dict, List, Optional

from config import BASE_DIR

logger = logging.getLogger("services.incident_store")

INCIDENTS_PATH = BASE_DIR / "data/incidents.jsonl"

REGISTER_MAX_TOPICS = 5

# Tokens numericos verificados del incidente (ratios 9/50, rangos 80->30,
# porcentajes 38%, miles 1,035, unidades 85 min, 2h->1h). Fuente de los
# strings obligatorios del gate. Se descartan enteros sueltos de 1-2 digitos
# sin unidad ni formato propio: '1' y '2' aparecen por casualidad en casi
# cualquier texto tecnico y el gate pasaria sin citar el incidente.
_FIGURE_TOKEN_RE = re.compile(r"\d[\d.,:xX+~\-→/>h%]*\d[h%]?|\d")
_NEXT_WORD_RE = re.compile(r"[A-Za-z]+")

# Unidades/contextos que vuelven distintivo a un entero corto (1-2 digitos):
# "85 min", "0 replies", "4 rejections". Unidades genericas (posts, comments,
# days, metric) NO salvan: son coincidencia facil en cualquier texto tecnico.
_DISTINCTIVE_UNITS = {
    "min", "mins", "minute", "minutes", "h", "hours", "hour", "ms", "sec",
    "seconds", "matches", "replies", "attempts", "rejections", "openings",
    "apertures", "lines", "rows", "cycles", "slots", "writes", "tests",
    "per", "of",
}
_SYMBOL_CHARS = "/,.:xX+~→>"


def _is_distinctive_figure(token: str, next_word: str) -> bool:
    """True si la cifra no puede aparecer por casualidad en otro contexto:
    formato propio (ratio, rango, miles, decimal, %), 3+ digitos, o unidad
    especifica adjunta."""
    if any(ch in token for ch in _SYMBOL_CHARS):
        return True
    if token.endswith("%"):
        return True
    if len(token) >= 3:
        return True
    if next_word and next_word.lower() in _DISTINCTIVE_UNITS:
        return True
    return False


def extract_incident_figures(incident: Optional[Dict], max_figures: int = 6) -> List[str]:
    """Cifras DISTINTIVAS del incidente como strings canonicos (ej. '410/410',
    '80->30', '9/50', '38%', '1,035', '247', '85 min').

    El gate de Phase A exige que el body incluya al menos 2 de ellas (o la
    unica que haya, si tras filtrar quedo una): la diferenciacion del post son
    estos numeros, no la narrativa. Enteros sueltos de 1-2 digitos sin unidad
    ni formato se descartan ('2', '1', '30' suelto) por no ser distintivos.

    Fuentes: real_numbers (principal) y symptom (fallback)."""
    if not incident:
        return []
    sources = [
        str(incident.get("real_numbers") or ""),
        str(incident.get("symptom") or ""),
    ]
    figures: List[str] = []
    for src in sources:
        for m in _FIGURE_TOKEN_RE.finditer(src):
            token = m.group(0).strip()
            if not token:
                continue
            rest = src[m.end():].lstrip()
            nxt = _NEXT_WORD_RE.match(rest)
            next_word = nxt.group(0) if nxt else ""
            if not _is_distinctive_figure(token, next_word):
                continue
            if token in figures:
                continue
            figures.append(token)
            if len(figures) >= max_figures:
                return figures
    return figures


def load_incidents() -> List[Dict]:
    """Carga las entradas del store (append-only JSONL). Ilegibles se ignoran."""
    incidents: List[Dict] = []
    if not INCIDENTS_PATH.exists():
        return incidents
    try:
        for line in INCIDENTS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Incident store: linea ilegible ignorada")
                continue
            if isinstance(record, dict) and record.get("id"):
                incidents.append(record)
    except OSError as e:
        logger.warning("Incident store: no se pudo leer %s: %s", INCIDENTS_PATH, e)
    return incidents


def save_incidents(incidents: List[Dict]) -> None:
    """Sobrescribe el store completo. Solo para marcar 'used'; append-only en el resto."""
    try:
        INCIDENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with INCIDENTS_PATH.open("w", encoding="utf-8") as f:
            for inc in incidents:
                f.write(json.dumps(inc, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Incident store: no se pudo escribir %s: %s", INCIDENTS_PATH, e)


def get_unused_incident() -> Optional[Dict]:
    """Primer incidente sin usar, o None si no queda ninguno."""
    for inc in load_incidents():
        if not inc.get("used"):
            return inc
    return None


def get_incident_by_id(incident_id: str) -> Optional[Dict]:
    for inc in load_incidents():
        if inc.get("id") == incident_id:
            return inc
    return None


def mark_incident_used(incident_id: str) -> bool:
    """Marca 'used': True (persistido). Devuelve True si cambio algo.

    Se llama SOLO al publicar el post (no al generar): si el gate de calidad
    rechaza el intento, el incidente queda disponible para el proximo ciclo.
    """
    incidents = load_incidents()
    changed = False
    for inc in incidents:
        if inc.get("id") == incident_id and not inc.get("used"):
            inc["used"] = True
            changed = True
    if changed:
        save_incidents(incidents)
    return changed


def register_incidents(agenda=None, max_topics: int = REGISTER_MAX_TOPICS) -> int:
    """Registra incidentes sin usar como topics en la research_agenda
    (source='own_incident:<id>', el mismo patron que postmortem_source).

    Idempotente: add_topic() dedup por nombre. No cuenta los topics ya
    registrados, asi que con un store de N incidentes y un max_topics menor,
    los ciclos siguientes completan la cola. Solo guarda la agenda si agrego
    algo. Devuelve cuantos se agregaron.
    """
    try:
        if agenda is None:
            from services.research_agenda import load_agenda
            agenda = load_agenda()
        existing = {t.get("topic") for t in agenda.pending_topics}
        added = 0
        for inc in load_incidents():
            if inc.get("used"):
                continue
            title = str(inc.get("title", "")).strip()
            if not title or title in existing:
                continue
            incident_id = str(inc.get("id", ""))
            agenda.add_topic(
                topic=title,
                source=f"own_incident:{incident_id}" if incident_id else "own_incident",
                tags=["own_incident", "own", "verifiable"],
            )
            existing.add(title)
            added += 1
            if added >= max_topics:
                break
        if added:
            from services.research_agenda import save_agenda
            save_agenda(agenda)
        if added:
            logger.info("Incident store: %d incidente(s) registrados en research_agenda", added)
        return added
    except Exception as e:
        logger.warning("Incident store: error registrando incidentes: %s", e)
        return 0
