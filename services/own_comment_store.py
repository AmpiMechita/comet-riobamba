# -*- coding: utf-8 -*-
"""
OwnCommentStore — Wrapper around DedupStore for tracking own comments.
Used by Phase C to track which posts we've already commented on.
"""
import logging
from typing import Optional

from services.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class OwnCommentStore:
    """Wrapper around DedupStore for Phase C own comment tracking."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.dedup = DedupStore(db_path)
    
    async def has_commented(self, post_id: str) -> bool:
        """Retorna True si ya comentamos en este post."""
        try:
            comment_ids = self.dedup.get_agent_comment_ids().get(post_id, [])
            return len(comment_ids) > 0
        except Exception as e:
            logger.warning(f"OwnCommentStore.has_commented failed: {e}")
            return False
    
    async def log_comment(self, post_id: str, comment_id: str) -> None:
        """Registra que comentamos en este post."""
        try:
            self.dedup.add_agent_comment(post_id, comment_id)
            logger.debug(f"OwnCommentStore: logged comment {comment_id} for post {post_id}")
        except Exception as e:
            logger.warning(f"OwnCommentStore.log_comment failed: {e}")
    
    async def get_comment_count(self, post_id: str) -> int:
        """Retorna el número de comentarios nuestros en un post."""
        try:
            comment_ids = self.dedup.get_agent_comment_ids().get(post_id, [])
            return len(comment_ids)
        except Exception:
            return 0


# Para compatibilidad con código existente que use la clase directamente
__all__ = ["OwnCommentStore"]