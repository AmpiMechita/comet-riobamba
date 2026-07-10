# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v4.2.2 - Deduplicación semántica ligera (Fase A)

Este módulo implementa una capa opcional de deduplicación semántica:

- Usa sentence-transformers para obtener embeddings de texto.
- Calcula similitud de coseno entre el post candidato y posts recientes.
- Si alguna similitud supera un umbral configurable, marca el texto como "similar".
- Persiste embeddings en la misma base de datos SQLite que services/persistence.py.

Dependencias opcionales:
    pip install -U sentence-transformers

Si la librería no está disponible, el módulo se degrada a no deduplicar
(retorna siempre False en is_semantically_similar_to_recent()).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pathlib import Path

from services.persistence import get_conn, init_db

logger = logging.getLogger("services.semantic_dedup")

# Modelo por defecto (ligero, recomendado para similitud de frases)[web:60][web:68]
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Estado global simple para modelo (lazy load)
_SENTENCE_MODEL = None
_SENTENCE_MODEL_NAME = None

# Tabla utilizada en SQLite
SEMANTIC_TABLE_NAME = "semantic_embeddings"


# ============================================================
# Utilidades internas
# ============================================================

def _ensure_table_exists() -> None:
    """
    Crea la tabla semantic_embeddings si no existe.
    Es independiente de init_db() principal, pero reutiliza la misma conexión.
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SEMANTIC_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                topic TEXT,
                text_hash TEXT,
                embedding_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )


def _load_sentence_model(model_name: str = DEFAULT_MODEL_NAME):
    """
    Carga el modelo de sentence-transformers de forma lazy.
    Si no está disponible, lanza ImportError.
    """
    global _SENTENCE_MODEL, _SENTENCE_MODEL_NAME
    if _SENTENCE_MODEL is not None:
        return _SENTENCE_MODEL

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers no está instalado. "
            "Instala con: pip install -U sentence-transformers"
        ) from exc

    logger.info(f"SemanticDedup: cargando modelo de embeddings '{model_name}'...")
    model = SentenceTransformer(model_name)
    _SENTENCE_MODEL = model
    _SENTENCE_MODEL_NAME = model_name
    logger.info("SemanticDedup: modelo cargado correctamente.")
    return model


def _embed_text(text: str, model_name: str = DEFAULT_MODEL_NAME) -> List[float]:
    """
    Devuelve el embedding del texto como lista de floats.
    """
    model = _load_sentence_model(model_name)
    # encode devuelve un vector; convert_to_numpy=True para lista/JSON
    emb = model.encode(text, convert_to_numpy=True)
    return emb.tolist()


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    Calcula la similitud de coseno entre dos vectores numéricos.[web:58][web:65]
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


# ============================================================
# API pública
# ============================================================

def store_semantic_embedding(
    post_id: Optional[str],
    topic: Optional[str],
    text_hash: Optional[str],
    embedding: List[float],
) -> None:
    """
    Persiste el embedding en la tabla semantic_embeddings.

    - post_id: ID de Moltbook (si se conoce).
    - topic: tópico lógico del contenido.
    - text_hash: hash del texto (opcional, para debugging / búsqueda rápida).
    - embedding: lista de floats (embedding del texto).
    """
    _ensure_table_exists()

    payload = embedding
    embedding_json = json.dumps(payload, ensure_ascii=False)

    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO {SEMANTIC_TABLE_NAME} (post_id, topic, text_hash, embedding_json)
            VALUES (?, ?, ?, ?)
            """,
            (post_id, topic, text_hash, embedding_json),
        )


def _load_recent_embeddings(window_days: int) -> List[Dict[str, Any]]:
    """
    Carga embeddings de posts recientes dentro de la ventana indicada.
    """
    _ensure_table_exists()
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, post_id, topic, text_hash, embedding_json, created_at
            FROM {SEMANTIC_TABLE_NAME}
            WHERE created_at >= datetime('now', ?)
            ORDER BY id DESC
            """,
            (f"-{window_days} days",),
        ).fetchall()

    result: List[Dict[str, Any]] = []
    for row in rows:
        emb_list = []
        try:
            emb_list = json.loads(row[4])
        except Exception:
            logger.warning("SemanticDedup: embedding_json no válido, se omite fila id=%s", row[0])
            continue

        result.append(
            {
                "id": row[0],
                "post_id": row[1],
                "topic": row[2],
                "text_hash": row[3],
                "embedding": emb_list,
                "created_at": row[5],
            }
        )
    return result


def is_semantically_similar_to_recent(
    text: str,
    *,
    threshold: float = 0.85,
    window_days: int = 7,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Comprueba si el texto es semánticamente similar a algunos posts recientes.

    Retorna (is_similar, best_match_info):

    - is_similar: True si alguna similitud >= threshold.
    - best_match_info: dict con info del mejor match, o None si no hay match relevante.

    Si sentence-transformers no está instalado o falla, registra un warning
    y retorna (False, None) (es decir, no bloquea generación).
    """
    if not text or not isinstance(text, str):
        return False, None

    try:
        candidate_emb = _embed_text(text, model_name=model_name)
    except ImportError as e:
        logger.warning("SemanticDedup: sentence-transformers no disponible: %s", e)
        return False, None
    except Exception as e:
        logger.warning("SemanticDedup: error obteniendo embedding: %s", e)
        return False, None

    recent = _load_recent_embeddings(window_days=window_days)
    if not recent:
        return False, None

    best_sim = -1.0
    best_row: Optional[Dict[str, Any]] = None

    for row in recent:
        emb = row["embedding"]
        sim = _cosine_similarity(candidate_emb, emb)
        if sim > best_sim:
            best_sim = sim
            best_row = row

    if best_sim >= threshold and best_row is not None:
        logger.info(
            "SemanticDedup: texto similar detectado (similarity=%.3f, threshold=%.3f, match_id=%s)",
            best_sim,
            threshold,
            best_row["id"],
        )
        match_info = dict(best_row)
        match_info["similarity"] = best_sim
        return True, match_info

    return False, None


# ============================================================
# Helper para integración con Fase A
# ============================================================

def dedup_and_store_for_phase_a(
    text: str,
    *,
    post_id: Optional[str],
    topic: Optional[str],
    text_hash: Optional[str],
    threshold: float = 0.85,
    window_days: int = 7,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Helper pensado para ser llamado desde PhaseAContentGeneration:

        similar, match = dedup_and_store_for_phase_a(
            post_text,
            post_id=None,
            topic=topic,
            text_hash=some_hash,
        )

    Comportamiento:
    - Calcula embedding del texto.
    - Comprueba similitud con ventana reciente.
    - Si NO es similar (similar=False), guarda el embedding en la BD.
    - Si es similar (similar=True), NO guarda el embedding (asumiendo que se descartará).

    Devuelve (is_similar, match_info).
    """
    is_similar, match_info = is_semantically_similar_to_recent(
        text,
        threshold=threshold,
        window_days=window_days,
        model_name=model_name,
    )

    if not is_similar:
        try:
            emb = _embed_text(text, model_name=model_name)
            store_semantic_embedding(
                post_id=post_id,
                topic=topic,
                text_hash=text_hash,
                embedding=emb,
            )
        except ImportError as e:
            logger.warning("SemanticDedup: no se pudo guardar embedding (sentence-transformers no instalado): %s", e)
        except Exception as e:
            logger.warning("SemanticDedup: error guardando embedding: %s", e)

    return is_similar, match_info