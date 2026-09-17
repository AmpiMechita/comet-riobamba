# -*- coding: utf-8 -*-
"""
Auditor de calidad para posts dry-run (julio-agosto 2026).

Aplica filtros automáticos y gates de calidad antes de re-publicar.

Uso:
    python scripts/audit_dryrun_quality.py

Genera:
    - data/dryrun_audit_report.csv (reporte completo)
    - data/dryrun_approved_posts.json (posts aprobados para publicación)
    - data/dryrun_rejected_posts.json (posts rechazados)
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

PUBLISHED_POSTS_PATH = Path("data/published_posts.json")
AUDIT_REPORT_PATH = Path("data/dryrun_audit_report.csv")
APPROVED_POSTS_PATH = Path("data/dryrun_approved_posts.json")
REJECTED_POSTS_PATH = Path("data/dryrun_rejected_posts.json")
SEPTEMBER_POSTS_PATH = Path("data/september_topics.txt")

# ── Criterios de calidad ─────────────────────────────────────

MIN_BODY_LENGTH = 300  # Posts muy cortos = baja calidad
MAX_TOPIC_FREQUENCY = 3  # Máximo posts por tema (evitar repetitivo)
GENERIC_TOPIC_PATTERNS = [
    r"production agent engineering implications",
    r"implications of the paper",
    r"arXiv:\d+\.\d+",
]

# Temas a excluir manualmente (ajustar según necesidad)
EXCLUDED_TOPICS = [
    # Agregar temas específicos aquí si se desea excluir
]


@dataclass
class AuditResult:
    post_id: str
    topic: str
    published_at: str
    body_length: int
    status: str  # "approved", "rejected", "manual_review"
    rejection_reasons: List[str]
    quality_score: int  # 1-5
    notes: str = ""


def load_published_posts() -> List[Dict[str, Any]]:
    """Cargar posts de published_posts.json."""
    if not PUBLISHED_POSTS_PATH.exists():
        logger.error(f"No existe {PUBLISHED_POSTS_PATH}")
        return []
    
    with open(PUBLISHED_POSTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "posts" in data:
        return data["posts"]
    else:
        logger.error(f"Formato desconocido en {PUBLISHED_POSTS_PATH}")
        return []


def filter_dryrun_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filtrar posts de julio-agosto 2026 (períº¾odo dry-run)."""
    dryrun_posts = []
    
    for post in posts:
        try:
            published_at = post.get("published_at", "")
            if isinstance(published_at, str):
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            else:
                dt = published_at
            
            # Filtrar julio-agosto 2026
            if dt.year == 2026 and dt.month in [7, 8]:
                dryrun_posts.append(post)
        except Exception as e:
            logger.warning(f"Error parseando fecha de post {post.get('post_id', 'unknown')}: {e}")
    
    logger.info(f"Posts dry-run encontrados: {len(dryrun_posts)} de {len(posts)} totales")
    return dryrun_posts


def load_september_topics() -> List[str]:
    """Cargar temas de septiembre 2026 (ya publicados)."""
    posts = load_published_posts()
    september_topics = []
    
    for post in posts:
        try:
            published_at = post.get("published_at", "")
            if isinstance(published_at, str):
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            else:
                dt = published_at
            
            if dt.year == 2026 and dt.month == 9:
                topic = post.get("topic", "").strip()
                if topic:
                    september_topics.append(topic.lower())
        except:
            pass
    
    return september_topics


def extract_topic_key(topic: str) -> str:
    """Extraer clave de tema para agrupaciÃ³n (normalizar)."""
    # Eliminar prefijos genÃ©ricos
    topic = re.sub(r"^production agent engineering implications of the paper\s*", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"^observability and tracing in\s*", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\(arXiv:\d+\.\d+v\d+\)", "", topic).strip()
    topic = topic.split(":")[0].strip()  # Tomar primera parte antes de ":"
    return topic.lower()[:80]  # Truncar para evitar diferencias menores


def has_generic_topic(topic: str) -> bool:
    """Verificar si el tema es un template genÃ©rico."""
    for pattern in GENERIC_TOPIC_PATTERNS:
        if re.search(pattern, topic, re.IGNORECASE):
            return True
    return False


def has_outdated_references(body: str) -> bool:
    """Verificar si el post tiene referencias temporales desactualizadas."""
    # Buscar referencias a "julio 2026", "agosto 2026", "este mes", etc.
    outdated_patterns = [
        r"\b(july|agosto|julio)\s+2026\b",
        r"\bthis\s+month\b",
        r"\blast\s+week\b",
        r"\brecent(ly)?\b",
    ]
    
    body_lower = body.lower()
    for pattern in outdated_patterns:
        if re.search(pattern, body_lower):
            return True
    
    return False


def text_has_fabricated_measurement(text: str) -> bool:
    """Gate de calidad: detectar mediciones fabricadas."""
    # Patrones de mediciones especÃ¬ficas (ej. "40% improvement", "3.2x faster")
    measurement_patterns = [
        r"\b(\d+\.?\d*)\s*(%|percent|times|x)\s*(improvement|increase|decrease|reduction|faster|slower)\b",
        r"\b(\d+\.?\d*)\s*(ms|seconds|minutes|hours)\b",
    ]
    
    for pattern in measurement_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Verificar si hay calificadores ("up to", "approximately", "about")
            if not re.search(r"\b(up to|approximately|about|around|roughly)\b", text, re.IGNORECASE):
                return True
    
    return False


def text_has_unverifiable_historical_claim(text: str) -> bool:
    """Gate de calidad: detectar afirmaciones histÃ³ricas no verificables."""
    # Patrones de afirmaciones histÃ³ricas especÃ¬ficas
    historical_patterns = [
        r"\bin\s+(19\d{2}|20\d{2})\b",  # AÃ±os especÃ¬ficos
        r"\b(invented|discovered|created|published)\s+by\b",
        r"\b(according to|as reported by|based on)\s+\w+\b",
    ]
    
    for pattern in historical_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False


def audit_post(post: Dict[str, Any], topic_counts: Dict[str, int], september_topics: List[str]) -> AuditResult:
    """Auditar un post individual. Retorna resultado."""
    post_id = post.get("post_id", "unknown")
    topic = post.get("topic", "")
    body = post.get("body", "")
    published_at = post.get("published_at", "")
    
    rejection_reasons = []
    quality_score = 5  # Comienza en 5, se reduce por problemas
    status = "approved"
    notes = []
    
    # 1. Longitud mÃ¬nima
    body_length = len(body)
    if body_length < MIN_BODY_LENGTH:
        rejection_reasons.append(f"body_too_short ({body_length} chars < {MIN_BODY_LENGTH})")
        quality_score -= 2
        status = "rejected"
    
    # 2. Tema genÃ©rico
    if has_generic_topic(topic):
        rejection_reasons.append("generic_topic_template")
        quality_score -= 1
        if status == "approved":
            status = "manual_review"
    
    # 3. Tema excluido manualmente
    topic_lower = topic.lower()
    for excluded in EXCLUDED_TOPICS:
        if excluded.lower() in topic_lower:
            rejection_reasons.append(f"excluded_topic ({excluded})")
            status = "rejected"
            quality_score -= 2
    
    # 4. Frecuencia de tema (evitar repetitivo)
    topic_key = extract_topic_key(topic)
    if topic_counts.get(topic_key, 0) > MAX_TOPIC_FREQUENCY:
        rejection_reasons.append(f"topic_overused ({topic_counts[topic_key]} > {MAX_TOPIC_FREQUENCY})")
        quality_score -= 1
        if status == "approved":
            status = "manual_review"
    
    # 5. Referencias desactualizadas
    if has_outdated_references(body):
        rejection_reasons.append("outdated_temporal_references")
        quality_score -= 1
        notes.append("Revisar vigencia de referencias temporales")
    
    # 6. Gate: mediciones fabricadas
    if text_has_fabricated_measurement(body):
        rejection_reasons.append("fabricated_measurement_detected")
        quality_score -= 2
        status = "rejected"
    
    # 7. Gate: afirmaciones histÃ³ricas no verificables
    if text_has_unverifiable_historical_claim(body):
        rejection_reasons.append("unverifiable_historical_claim")
        quality_score -= 1
        notes.append("Verificar fuentes histÃ³ricas")
    
    # 8. Similaridad con posts de septiembre
    topic_lower = topic.lower()
    for sep_topic in september_topics:
        if topic_lower in sep_topic or sep_topic in topic_lower:
            rejection_reasons.append("duplicate_september_topic")
            quality_score -= 2
            status = "rejected"
            notes.append("Tema ya publicado en septiembre")
            break
    
    # Asegurar score en rango 1-5
    quality_score = max(1, min(5, quality_score))
    
    # Determinar status final
    if quality_score <= 2:
        status = "rejected"
    elif quality_score == 3:
        status = "manual_review"
    elif quality_score >= 4:
        status = "approved"
    
    return AuditResult(
        post_id=post_id,
        topic=topic[:100],  # Truncar para CSV
        published_at=str(published_at)[:19],
        body_length=body_length,
        status=status,
        rejection_reasons=rejection_reasons,
        quality_score=quality_score,
        notes="; ".join(notes)
    )


def run_audit():
    """Ejecutar auditorÃ¬a completa."""
    logger.info("ð§ª¦ Iniciando auditorÃ¬a de calidad para posts dry-run")
    
    # Cargar posts
    posts = load_published_posts()
    if not posts:
        logger.error("No hay posts para auditar")
        return
    
    # Filtrar dry-run (julio-agosto 2026)
    dryrun_posts = filter_dryrun_posts(posts)
    if not dryrun_posts:
        logger.info("No se encontraron posts dry-run (julio-agosto 2026)")
        return
    
    logger.info(f"ð§«¦ Procesando {len(dryrun_posts)} posts dry-run")
    
    # Cargar temas de septiembre (para deduplicaciÃ³n)
    september_topics = load_september_topics()
    logger.info(f"Temas de septiembre cargados: {len(september_topics)}")
    
    # Contar frecuencia de temas
    topic_counts: Dict[str, int] = {}
    for post in dryrun_posts:
        topic_key = extract_topic_key(post.get("topic", ""))
        topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1
    
    logger.info(f"Temas Ãnicos encontrados: {len(topic_counts)}")
    
    # Auditar cada post
    results: List[AuditResult] = []
    approved_posts = []
    rejected_posts = []
    
    for i, post in enumerate(dryrun_posts, 1):
        if i % 50 == 0:
            logger.info(f"[{i}/{len(dryrun_posts)}] Auditando posts...")
        
        result = audit_post(post, topic_counts, september_topics)
        results.append(result)
        
        if result.status == "approved":
            approved_posts.append(post)
        elif result.status in ["rejected", "manual_review"]:
            rejected_posts.append({
                "post": post,
                "result": asdict(result)
            })
    
    # Guardar reporte CSV
    logger.info(f"ð§«¦ Guardando reporte en {AUDIT_REPORT_PATH}")
    with open(AUDIT_REPORT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write("post_id,topic,published_at,body_length,status,quality_score,rejection_reasons,notes\n")
        for r in results:
            topic_escaped = r.topic.replace('"', '""').replace("\n", " ")
            reasons_escaped = "; ".join(r.rejection_reasons).replace('"', '""')
            notes_escaped = r.notes.replace('"', '""').replace("\n", " ")
            f.write(f'{r.post_id},"{topic_escaped}",{r.published_at},{r.body_length},{r.status},{r.quality_score},"{reasons_escaped}","{notes_escaped}"\n')
    
    # Guardar posts aprobados
    logger.info(f"ð§«¦ Guardando {len(approved_posts)} posts aprobados en {APPROVED_POSTS_PATH}")
    with open(APPROVED_POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(approved_posts, f, indent=2, ensure_ascii=False)
    
    # Guardar posts rechazados
    logger.info(f"ð§«¦ Guardando {len(rejected_posts)} posts rechazados en {REJECTED_POSTS_PATH}")
    with open(REJECTED_POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(rejected_posts, f, indent=2, ensure_ascii=False)
    
    # Resumen
    approved_count = len(approved_posts)
    rejected_count = len([r for r in results if r.status == "rejected"])
    manual_review_count = len([r for r in results if r.status == "manual_review"])
    
    logger.info("â§ª Resumen de auditorÃ¬a:")
    logger.info(f"  âÂ§ Aprobados: {approved_count} ({approved_count/len(results)*100:.1f}%)")
    logger.info(f"  âÂ§ Rechazados: {rejected_count} ({rejected_count/len(results)*100:.1f}%)")
    logger.info(f"  âÂ§ RevisiÃ³n manual: {manual_review_count} ({manual_review_count/len(results)*100:.1f}%)")
    logger.info(f"â§ª Reporte completo: {AUDIT_REPORT_PATH}")
    logger.info(f"â§ª Posts aprobados: {APPROVED_POSTS_PATH}")
    logger.info(f"â§ª Posts rechazados: {REJECTED_POSTS_PATH}")


if __name__ == "__main__":
    run_audit()