# -*- coding: utf-8 -*-
"""
Phase C: Comentar posts de agentes de la watchlist apenas publican.

Esta fase opera de forma independiente a Phase B (que solo responde en posts propios).
Phase C lee el feed global, filtra por autores de la watchlist y genera comentarios
de alta calidad en sus posts nuevos.

Configuraciones esperadas en behavior_cfg o .env:
  - PHASE_C_ENABLED: true/false
  - PHASE_C_MAX_COMMENTS_PER_CYCLE: int (ej. 3)
  - PHASE_C_MAX_COST_USD_PER_CYCLE: float (ej. 0.15)
  - PHASE_C_ONLY_WATCHLIST: true (recomendado)
  - PHASE_C_QUALITY_GATE_ENABLED: true
  - WATCHLIST_FILE: ruta al JSON de watchlist (ej. config/top_agents_watchlist.json)
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.moltbook_api_client import MoltbookAPIClient
from services.model_cascade import ModelCascade
from services.quota_manager import QuotaManager
from services.dedup_store import DedupStore
from services.own_comment_store import OwnCommentStore

logger = logging.getLogger(__name__)


class PhaseCWatchlist:
    def __init__(
        self,
        moltbook_client: MoltbookAPIClient,
        model_cascade: ModelCascade,
        dedup_store: DedupStore,
        own_comment_store: OwnCommentStore,
        watchlist_file: str,
        quota_manager: Optional[QuotaManager] = None,
        max_comments_per_cycle: int = 3,
        max_cost_usd_per_cycle: float = 0.15,
        quality_gate_enabled: bool = True,
        only_watchlist: bool = True,
        self_agent_id: Optional[str] = None,
    ):
        self.moltbook = moltbook_client
        self.model_cascade = model_cascade
        self.quota_manager = quota_manager
        self.dedup_store = dedup_store
        self.own_comment_store = own_comment_store
        self.watchlist_file = watchlist_file
        self.max_comments_per_cycle = max_comments_per_cycle
        self.max_cost_usd_per_cycle = max_cost_usd_per_cycle
        self.quality_gate_enabled = quality_gate_enabled
        self.only_watchlist = only_watchlist
        self.self_agent_id = self_agent_id or os.getenv("AGENT_ID")
        
        self.watchlist: List[str] = []
        self._load_watchlist()
    
    def _load_watchlist(self) -> None:
        """Carga la watchlist desde el archivo JSON."""
        try:
            if os.path.exists(self.watchlist_file):
                with open(self.watchlist_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Soportar tanto {"top_agents": [...]} como lista directa
                    if isinstance(data, dict) and "top_agents" in data:
                        raw = data["top_agents"]
                    elif isinstance(data, list):
                        raw = data
                    else:
                        logger.warning(f"Watchlist file {self.watchlist_file} tiene formato inesperado")
                        raw = []
                    # Extraer solo usernames (soportar objetos {"username": "..."} o strings directos)
                    self.watchlist = []
                    for item in raw:
                        if isinstance(item, dict) and "username" in item:
                            self.watchlist.append(item["username"])
                        elif isinstance(item, str):
                            self.watchlist.append(item)
                    logger.info(f"Phase C: watchlist cargada con {len(self.watchlist)} agentes")
            else:
                logger.warning(f"Watchlist file {self.watchlist_file} no existe")
                self.watchlist = []
        except Exception as e:
            logger.error(f"Error cargando watchlist: {e}")
            self.watchlist = []
    
    async def run(self) -> Dict[str, Any]:
        """
        Ejecuta Phase C: escanea feed global, filtra por watchlist y comenta.
        
        Retorna:
            Dict con métricas: posts_leidos, watchlist_posts, candidatos, comentarios_publicados, costo_total
        """
        start_time = time.time()
        metrics = {
            "posts_leidos": 0,
            "watchlist_posts": 0,
            "candidatos": 0,
            "comentarios_publicados": 0,
            "costo_total": 0.0,
            "errores": 0,
        }
        
        logger.info("Phase C: iniciando escaneo de feed global")
        
        # 1. Leer feed global (posts recientes)
        try:
            recent_posts = self.moltbook.fetch_posts(limit=50, sort="new")
            metrics["posts_leidos"] = len(recent_posts)
            logger.info(f"Phase C: {len(recent_posts)} posts leidos del feed")
        except Exception as e:
            logger.error(f"Phase C: error leyendo feed: {e}")
            metrics["errores"] += 1
            return metrics
        
        # 2. Filtrar por watchlist
        watchlist_posts = []
        for post in recent_posts:
            author_id = post.get("author_id") or post.get("author", {}).get("id")
            
            # Saltar posts propios
            if author_id == self.self_agent_id:
                continue
            
            # Si only_watchlist, solo considerar autores en watchlist
            if self.only_watchlist and author_id not in self.watchlist:
                continue
            
            watchlist_posts.append(post)
        
        metrics["watchlist_posts"] = len(watchlist_posts)
        logger.info(f"Phase C: {len(watchlist_posts)} posts de watchlist encontrados")
        
        if not watchlist_posts:
            return metrics
        
        # 3. Priorizar por señales de oportunidad
        candidates = self._score_posts(watchlist_posts)
        candidates.sort(reverse=True, key=lambda x: x[0])
        metrics["candidatos"] = len(candidates)
        
        # 4. Limitar procesamiento por ciclo
        processed = 0
        ciclo_cost = 0.0
        
        for score, post in candidates:
            if processed >= self.max_comments_per_cycle:
                logger.info(f"Phase C: alcanzado max_comments_per_cycle ({self.max_comments_per_cycle})")
                break
            
            if ciclo_cost >= self.max_cost_usd_per_cycle:
                logger.info(f"Phase C: alcanzado max_cost_usd_per_cycle (${self.max_cost_usd_per_cycle:.2f})")
                break
            
            post_id = post.get("id")
            if not post_id:
                continue
            
            # 5. Verificar si ya comentamos en este post
            if await self.own_comment_store.has_commented(post_id):
                logger.debug(f"Phase C: ya comentamos en post {post_id[:8]}…")
                continue
            
            # 6. Generar comentario de alta calidad
            try:
                comment = await self._generate_comment(post)
            except Exception as e:
                logger.error(f"Phase C: error generando comentario: {e}")
                metrics["errores"] += 1
                continue
            
            if not comment or len(comment.strip()) < 50:
                logger.warning(f"Phase C: comentario demasiado corto o vacío")
                continue
            
            # 7. Quality gate (opcional)
            if self.quality_gate_enabled:
                passes_quality = await self._quality_gate(comment, post)
                if not passes_quality:
                    logger.info(f"Phase C: comentario rechazado por quality gate")
                    continue
            
            # 8. Publicar comentario
            try:
                result = self.moltbook.create_comment(post_id, comment)
                if result.get("success") or result.get("id"):
                    comment_id = result.get("id") or result.get("comment_id")
                    await self.own_comment_store.log_comment(post_id, comment_id)
                    
                    # Capturar costo
                    cost = result.get("cost_usd", 0.0)
                    ciclo_cost += cost
                    processed += 1
                    
                    logger.info(
                        f"Phase C: comentario publicado en post {post_id[:8]}… "
                        f"(autor: {post.get('author', {}).get('name', 'unknown')}, "
                        f"costo: ${cost:.4f}, total ciclo: ${ciclo_cost:.4f})"
                    )
                else:
                    logger.warning(f"Phase C: fallo publicando comentario: {result}")
                    metrics["errores"] += 1
            except Exception as e:
                logger.error(f"Phase C: error publicando comentario: {e}")
                metrics["errores"] += 1
        
        metrics["comentarios_publicados"] = processed
        metrics["costo_total"] = ciclo_cost
        
        elapsed = time.time() - start_time
        logger.info(
            f"Phase C: completado en {elapsed:.2f}s | "
            f"posts={metrics['posts_leidos']}, watchlist={metrics['watchlist_posts']}, "
            f"candidatos={metrics['candidatos']}, publicados={metrics['comentarios_publicados']}, "
            f"costo=${metrics['costo_total']:.4f}"
        )
        
        return metrics
    
    def _score_posts(self, posts: List[Dict]) -> List[Tuple[int, Dict]]:
        """
        Prioriza posts por señales de oportunidad.
        
        Criterios:
          - +40: primer comentario (comments_count == 0)
          - +20: autor con karma alto (>5000)
          - +30: post muy reciente (<30 min)
          - +10: contiene keywords de la watchlist
          - +15: autor en watchlist (si only_watchlist es False)
        """
        scored = []
        
        for post in posts:
            score = 0
            
            # Señal: primer comentario
            comments_count = post.get("comments_count", 0)
            if comments_count == 0:
                score += 40
            
            # Señal: autor con karma alto
            author = post.get("author", {})
            author_karma = author.get("karma", 0)
            if author_karma > 5000:
                score += 20
            
            # Señal: post muy reciente
            published_at = post.get("published_at")
            if published_at:
                try:
                    # Asumir formato ISO 8601
                    pub_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    age_minutes = (datetime.now(timezone.utc) - pub_time).total_seconds() / 60
                    if age_minutes < 30:
                        score += 30
                except Exception:
                    pass
            
            # Señal: keywords tematicas
            body = post.get("body", "").lower()
            keywords = [
                "agent", "memory", "state", "reliability", "orchestration",
                "tool", "api", "context", "drift", "rollback"
            ]
            if any(kw in body for kw in keywords):
                score += 10
            
            # Señal: autor en watchlist (si only_watchlist es False)
            author_id = author.get("id")
            if not self.only_watchlist and author_id in self.watchlist:
                score += 15
            
            scored.append((score, post))
        
        return scored
    
    async def _generate_comment(self, post: Dict) -> str:
        """
        Genera un comentario de alta calidad para el post.
        
        El comentario debe:
          - Referirse a una premisa específica del post
          - Añadir mecanismo, prueba, límite o contraejemplo
          - Proponer una prueba falsable o decisión técnica
          - Máximo 2-3 oraciones densas
        """
        body = post.get("body", "")
        author = post.get("author", {}).get("name", "unknown")
        topic = post.get("topic", "")
        
        prompt = f"""
Eres un agente especialista en ingenieria de agentes de IA.
Vas a comentar un post de un agente reputado en Moltbook.

Post:
  Autor: {author}
  Tema: {topic}
  Cuerpo:
  {body}

Genera un comentario de 2-3 oraciones que:
  1. Se refiera a una premisa específica del post (no reformules el título)
  2. Añade mecanismo, prueba, límite o contraejemplo concreto
  3. Proponga una prueba falsable o decisión técnica accionable
  4. Evite preguntas retóricas al final
  5. Sea denso en contenido técnico, no relleno

Comentario:
"""
        
        try:
            result = await self.model_cascade.generate(
                prompt=prompt,
                tier="tier_pro",  # Usar modelo de mayor calidad para Phase C
                max_tokens=200,
            )
            comment = result.get("content", "").strip()
            return comment
        except Exception as e:
            logger.error(f"Error generando comentario Phase C: {e}")
            return ""
    
    async def _quality_gate(self, comment: str, post: Dict) -> bool:
        """
        Quality gate específico para Phase C.
        
        Criterios:
          - No repetir el título del post
          - Añadir mecanismo, prueba, límite o contraejemplo
          - Referirse a una premisa específica
          - Proponer prueba falsable o decisión técnica
          - Máximo 2-3 oraciones
          - No preguntas retóricas al final
        """
        # Longitud mínima y máxima
        if len(comment) < 80 or len(comment) > 600:
            logger.debug(f"Quality gate C: longitud inadecuada ({len(comment)} chars)")
            return False
        
        # No debe contener el título del post (aproximado por topic)
        topic = post.get("topic", "").lower()
        if topic and topic in comment.lower():
            logger.debug(f"Quality gate C: comentario repite el topic")
            return False
        
        # Debe contener señales de mecanismo o prueba
        mechanism_keywords = [
            "would test", "i would measure", "test this by", "mechanism",
            "boundary", "if-then", "experiment", "measure", "prove",
            "falsable", "decision", "trigger", "rollback"
        ]
        has_mechanism = any(kw in comment.lower() for kw in mechanism_keywords)
        
        if not has_mechanism:
            logger.debug(f"Quality gate C: no añade mecanismo o prueba")
            return False
        
        # No debe terminar con pregunta retórica
        if comment.rstrip().endswith("?"):
            logger.debug(f"Quality gate C: termina con pregunta retórica")
            return False
        
        return True


# Función helper para integrar en run_cycle()
async def run_phase_c_if_enabled(
    moltbook_client: MoltbookAPIClient,
    model_cascade: ModelCascade,
    config: Dict[str, Any],
    dedup_store: Optional[DedupStore] = None,
    own_comment_store: Optional[OwnCommentStore] = None,
    quota_manager: Optional[QuotaManager] = None,
) -> Optional[Dict[str, Any]]:
    """
    Ejecuta Phase C si está habilitada en la configuración.
    
    Args:
        config: Diccionario con behavior_cfg o variables de entorno
    
    Retorna:
        Metrics dict si Phase C se ejecutó, None si estaba deshabilitada
    """
    phase_c_enabled = config.get("phase_c_enabled", False)
    if not phase_c_enabled:
        return None
    
    watchlist_file = config.get("watchlist_file", "config/top_agents_watchlist.json")
    max_comments = config.get("phase_c_max_comments_per_cycle", 3)
    max_cost = config.get("phase_c_max_cost_usd_per_cycle", 0.15)
    quality_gate = config.get("phase_c_quality_gate_enabled", True)
    only_watchlist = config.get("phase_c_only_watchlist", True)
    self_agent_id = config.get("agent_id", os.getenv("AGENT_ID"))
    
    phase_c = PhaseCWatchlist(
        moltbook_client=moltbook_client,
        model_cascade=model_cascade,
        quota_manager=quota_manager,
        dedup_store=dedup_store,
        own_comment_store=own_comment_store,
        watchlist_file=watchlist_file,
        max_comments_per_cycle=max_comments,
        max_cost_usd_per_cycle=max_cost,
        quality_gate_enabled=quality_gate,
        only_watchlist=only_watchlist,
        self_agent_id=self_agent_id,
    )
    
    metrics = await phase_c.run()
    return metrics