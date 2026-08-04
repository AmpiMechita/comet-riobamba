# -*- coding: utf-8 -*-
"""
Post-mortem source: registra hallazgos REALES y verificables del propio
proyecto como topics en la research_agenda (source='postmortem_own').

Estrategia 4.3 (docs/ESTRATEGIA_MOLTBOOK_2026-07-21.md): el mejor post de
u/vina es una confesión de error propia (409 pts / 6,126 comentarios). El
mercado premia vulnerabilidad verificable. Cada entrada aqui es un incidente
documentado en el historial de git / docs — no inventado.

add_topic() hace dedup por nombre, asi que esta funcion es idempotente y
barata (sin LLM): se puede llamar en cada ciclo de Phase C.
"""

import logging
from typing import List, Optional

logger = logging.getLogger("services.postmortem_source")

# ── Incidentes reales del proyecto (verificables en git/docs) ──
# Cada entrada: (title, lesson, detail)
POSTMORTEMS: List[tuple] = [
    (
        "178 archivos 'modificados' que no estaban modificados: la mentira de CRLF",
        "El ruido de fin de linea (CRLF) hizo que git mostrara 178 y 14 archivos "
        "como cambiados sin estarlo, generando falsas alarmas de estado.",
        "Fix: configurar core.autocrlf y .gitattributes. Leccion: los artefactos "
        "de control de versiones mienten cuando la normalizacion no esta resuelta.",
    ),
    (
        "El bug de una sola palabra que rompia el import: Dict faltante",
        "services/topic_memory.py usaba Dict sin importarlo. Un detalle de una "
        "linea tiraba el modulo completo en runtime.",
        "Fix: agregar el import. Leccion: los errores mas caros en agentes "
        "autonomos son los que no se detectan en import time, sino horas despues "
        "en el primer uso real.",
    ),
    (
        "El outbox zombie: reintentar para siempre un comentario que jamas se publicaria",
        "Los errores 4xx (rechazo permanente) se trataban igual que los 5xx "
        "(transitorios), asi que el retry reintentaba lo imposible indefinidamente.",
        "Fix: clasificar 4xx como failed. Leccion: un retry sin clasificar el "
        "codigo de error no es resiliencia, es persistencia de la deuda.",
    ),
    (
        "El spend guard sin reset: proteger el presupuesto $5/dia que nunca se reiniciaba",
        "El guard diario de gasto LLM funcionaba, pero sin reset el contador se "
        "acumulaba y el tope se volvia inutil despues del primer dia.",
        "Fix: reset diario del contador. Leccion: los limites de costo solo "
        "protegen si su unidad de tiempo tambien se renueva.",
    ),
    (
        "Comandos de Telegram congelados: ignorar mensajes viejos, incluso los que el humano escribio",
        "El listener descartaba mensajes de mas de 60s como 'stale', incluyendo "
        "slash-commands que el operador habia tipeado deliberadamente.",
        "Fix: nunca descartar comandos explicitos por antiguedad. Leccion: el "
        "anti-spam no debe comerse la interfaz de control humana.",
    ),
    (
        "El scraper que migro y no aviso: la API legacy de patentes dejo de devolver JSON",
        "La API de PatentsView migro al Open Data Portal y respondia HTML. El "
        "scraper fallaba en silencio: datos vacios sin warning.",
        "Fix: skip visible sin credenciales + logging real. Leccion: un scraper "
        "que falla silenciosamente es peor que uno apagado — sabes que no tiene datos.",
    ),
]


def register_postmortems(agenda=None) -> int:
    """Registra los post-mortems no cubiertos en la research_agenda.

    Idempotente: add_topic() dedup por nombre. Devuelve cuantos se agregaron.
    """
    try:
        if agenda is None:
            from services.research_agenda import load_agenda
            agenda = load_agenda()
        added = 0
        for title, lesson, detail in POSTMORTEMS:
            agenda.add_topic(
                topic=title,
                source="postmortem_own",
                tags=["postmortem", "own", "verifiable"],
            )
            added += 1
        from services.research_agenda import save_agenda
        save_agenda(agenda)
        logger.info("Postmortem source: %d topics registrados en research_agenda", added)
        return added
    except Exception as e:
        logger.warning("Postmortem source: error registrando topics: %s", e)
        return 0
