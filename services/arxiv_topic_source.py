# -*- coding: utf-8 -*-
"""
ArXiv Topic Source

Fuente de temas auto-renovable para Fase A. Reemplaza la dependencia exclusiva
de la lista estática de 12 temas en EDITORIAL_CONFIG["topics"] (phase_a_content.py)
por papers reales y recientes de arXiv, con cita verificable (arXiv ID + titulo).

No publica nada por si mismo: solo agrega candidatos a la research agenda
(data/research_agenda.json) via add_topic(). choose_topic() en phase_a_content.py
ya prioriza la agenda por sobre la lista estatica, asi que no hace falta tocar
la logica de seleccion existente.

Uso manual:
    python -m services.arxiv_topic_source

No esta conectado automaticamente a ningun ciclo todavia -- eso es una decision
aparte (ver docs/ESTRATEGIA_MOLTBOOK_2026-07-21.md, punto 4.1).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List
from xml.etree import ElementTree as ET

import requests

from services.research_agenda import load_agenda, save_agenda

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Categorias + keywords alineadas con el vertical real de COMET (agentes en
# produccion, no investigacion academica pura).
DEFAULT_QUERY = (
    'cat:cs.AI AND (abs:agent OR abs:"multi-agent") '
    "AND (abs:reliability OR abs:failure OR abs:memory OR abs:orchestration "
    "OR abs:observability OR abs:production)"
)

# Prefijo que garantiza pasar el filtro _is_allowed_topic() de phase_a_content.py
# (requiere al menos una senal de ALLOWED_TOPIC_SIGNALS: "agent", "production", etc.)
TOPIC_PREFIX = "production agent engineering implications of"


def fetch_recent_papers(
    query: str = DEFAULT_QUERY, max_results: int = 8, timeout: int = 20
) -> List[Dict[str, str]]:
    """Trae papers recientes de arXiv que matcheen la query. No lanza excepcion
    si falla la red -- devuelve lista vacia y loguea el warning (mismo patron
    de manejo de errores que el resto del proyecto)."""
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    try:
        resp = requests.get(ARXIV_API_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("arxiv_topic_source: fetch failed: %s", e)
        return []
    return parse_arxiv_response(resp.text)


def parse_arxiv_response(xml_text: str) -> List[Dict[str, str]]:
    """Parsea el Atom XML de la API de arXiv. Aislado de fetch_recent_papers
    para poder testear sin red (ver tests/test_arxiv_topic_source.py)."""
    papers: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("arxiv_topic_source: XML parse failed: %s", e)
        return []
    for entry in root.findall("atom:entry", ARXIV_NS):
        id_el = entry.find("atom:id", ARXIV_NS)
        title_el = entry.find("atom:title", ARXIV_NS)
        summary_el = entry.find("atom:summary", ARXIV_NS)
        if id_el is None or title_el is None:
            continue
        raw_id = (id_el.text or "").strip()
        arxiv_id_match = re.search(r"abs/([\w.\-]+)", raw_id)
        arxiv_id = arxiv_id_match.group(1) if arxiv_id_match else raw_id
        title = " ".join((title_el.text or "").split())
        summary = " ".join((summary_el.text or "").split()) if summary_el is not None else ""
        if not title or not arxiv_id:
            continue
        papers.append({"id": arxiv_id, "title": title, "summary": summary[:500]})
    return papers


def build_topic_string(paper: Dict[str, str]) -> str:
    """Construye el string de tema que ve el LLM. Debe (a) pasar el filtro
    editorial de _is_allowed_topic() y (b) traer suficiente especificidad
    (titulo + arXiv ID) para que el post generado pueda citar la fuente real,
    igual que hace u/vina en Moltbook."""
    return (
        f'{TOPIC_PREFIX} the paper "{paper["title"]}" '
        f'(arXiv:{paper["id"]}) for production agent reliability and orchestration'
    )


def refresh_agenda_from_arxiv(query: str = DEFAULT_QUERY, max_results: int = 8) -> int:
    """Trae papers recientes y los agrega como pending_topics en la research
    agenda. No publica nada -- solo puebla candidatos que Fase A puede elegir
    en su proximo ciclo. Devuelve cuantos temas nuevos se agregaron (evita
    duplicados exactos por texto de tema)."""
    papers = fetch_recent_papers(query=query, max_results=max_results)
    if not papers:
        logger.info("arxiv_topic_source: no se obtuvieron papers, agenda sin cambios.")
        return 0

    agenda = load_agenda()
    existing_topics = {t["topic"] for t in agenda.pending_topics}
    added = 0
    for paper in papers:
        topic = build_topic_string(paper)
        if topic in existing_topics:
            continue
        agenda.add_topic(topic, source="arxiv", tags=["arxiv", paper["id"]])
        added += 1

    if added:
        save_agenda(agenda)
        logger.info("arxiv_topic_source: %d temas nuevos agregados desde arXiv.", added)
    return added


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = refresh_agenda_from_arxiv()
    print(f"Added {n} new topics from arXiv.")
