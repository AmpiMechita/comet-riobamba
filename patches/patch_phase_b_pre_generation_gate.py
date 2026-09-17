# -*- coding: utf-8 -*-
"""
Patch: Gate PRE-generacion en Phase B
Objetivo: Evitar llamadas al modelo cuando el post original contiene
          entidades no calificadas (Kafka, Python 3.9, etc.) que
          probablemente generaran un reply rechazado por ungrounded_named_entity.

Ubicacion: phases/phase_b/orchestrator.py
Insertar antes de: linea 2640 (llamada a _generate_reply_for_post)
"""

import re
from typing import Tuple, List

# Copia de las listas de quality_governor.py
EJEMPLOS_CONOCIDOS = [
    "kafka", "Einstein", "Newton", "Darwin", "Freud", "Jung",
    "Tesla", "Gutenberg", "Turing", "Shakespeare", "Picasso"
]

SOFTWARE_CONOCIDO = [
    "kafka", "python", "java", "javascript", "typescript", "node",
    "docker", "kubernetes", "redis", "postgres", "mysql", "mongodb",
    "nginx", "apache", "tensorflow", "pytorch", "transformers",
    "langchain", "llama", "mistral"
]


def _text_has_ungrounded_named_entity_simple(text: str) -> Tuple[bool, List[str]]:
    """
    Version simplificada del gate de quality_governor.py.
    Retorna (True, lista_entidades) si detecta entidades sin calificador.
    """
    text_lower = text.lower()
    
    # Verificar si tiene calificadores genericos
    tiene_calificador_generico = any([
        "ejemplo" in text_lower,
        "como" in text_lower,
        "like" in text_lower,
        "por ejemplo" in text_lower,
        "such as" in text_lower,
        "for example" in text_lower,
    ])
    
    entidades_sin_calificar = []
    for entidad in EJEMPLOS_CONOCIDOS:
        if entidad.lower() in text_lower and not tiene_calificador_generico:
            entidades_sin_calificar.append(entidad)
    
    return (len(entidades_sin_calificar) > 0, entidades_sin_calificar)


def _text_has_ungrounded_software_version_simple(text: str) -> Tuple[bool, List[str]]:
    """
    Version simplificada del gate de software versions.
    Retorna (True, lista_versiones) si detecta versiones sin calificador.
    """
    text_lower = text.lower()
    
    # Verificar si tiene calificadores
    tiene_calificador = any([
        "ejemplo" in text_lower,
        "como" in text_lower,
        "version" in text_lower,
        "release" in text_lower,
        "introduced" in text_lower,
        "since" in text_lower,
        "starting from" in text_lower,
        "for example" in text_lower,
    ])
    
    if tiene_calificador:
        return (False, [])
    
    versiones_sin_calificar = []
    for software in SOFTWARE_CONOCIDO:
        patron = rf"\b{software}\s+(\d+\.\d+(?:\.\d+)?)"
        matches = re.finditer(patron, text_lower, re.IGNORECASE)
        
        for match in matches:
            version_completa = match.group(0)
            versiones_sin_calificar.append(version_completa)
    
    return (len(versiones_sin_calificar) > 0, versiones_sin_calificar)


def should_skip_generation_pre_gate(post: dict) -> Tuple[bool, str]:
    """
    Gate PRE-generacion para Phase B.
    
    Retorna (True, motivo) si se debe SKIP la generacion del reply.
    Retorna (False, "") si se puede proceder con la generacion.
    
    Criterios:
    1. Post menciona entidades conocidas sin calificador.
    2. Post menciona versiones de software sin calificador.
    3. Post es demasiado corto para aportar valor (< 50 chars).
    """
    title = str(post.get("title") or "").strip()
    body = str(post.get("content") or post.get("body") or "").strip()
    text_completo = f"{title} {body}"
    
    # Criterio 1: Entidades nombradas sin calificador
    tiene_entidades, entidades = _text_has_ungrounded_named_entity_simple(text_completo)
    if tiene_entidades:
        return (True, f"ungrounded_entities_pre:{','.join(entidades)}")
    
    # Criterio 2: Versiones de software sin calificador
    tiene_versiones, versiones = _text_has_ungrounded_software_version_simple(text_completo)
    if tiene_versiones:
        return (True, f"ungrounded_versions_pre:{','.join(versiones)}")
    
    # Criterio 3: Post demasiado corto
    if len(body) < 50:
        return (True, "body_too_short_pre:<50chars")
    
    # Criterio 4: Post es solo pregunta sin contexto
    if body.endswith("?") and len(body.split()) < 10:
        return (True, "question_only_pre:<10words")
    
    return (False, "")


# ============================================================================
# PATCH PARA INSERTAR EN phases/phase_b/orchestrator.py
# ============================================================================
# 
# En la linea ~2640, antes de:
#   reply_text, claim = await self._generate_reply_for_post(...)
#
# Insertar:
# ============================================================================
#
#     # ── PRE-GENERATION GATE (patch 2026-08-31) ─────────────────────────────
#     skip_gen, motivo = should_skip_generation_pre_gate(post)
#     if skip_gen:
#         logger.info(
#             "Phase B: PRE-GENERATION GATE skip post_id=%s motivo=%s",
#             post.get("id"), motivo
#         )
#         continue  # Saltar este post, no gastar tokens
#     # ────────────────────────────────────────────────────────────────────────
#
#     reply_text, claim = await self._generate_reply_for_post(...)
#
# ============================================================================