"""
Topic Memory - v3.1.0
"""

import sqlite3
import hashlib
import re
import logging
from typing import List, Tuple, Optional
from datetime import datetime, timedelta
from pathlib import Path

from config import TOPIC_MEMORY_DB_PATH

logger = logging.getLogger(__name__)


class TopicMemory:
    
    def __init__(self, db_path: Path = None):
        self.db_path = db_path or TOPIC_MEMORY_DB_PATH
        self.conn = self._get_connection()
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_hash TEXT UNIQUE NOT NULL,
                topic_text TEXT NOT NULL,
                normalized_text TEXT,
                keywords TEXT,
                post_type TEXT DEFAULT 'original',
                platform TEXT DEFAULT 'moltbook',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cycle_number INTEGER
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_topic_hash ON topics(topic_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON topics(created_at)")
        self.conn.commit()
    
    def record_topic(self, text: str, post_type: str = "original", cycle_num: int = 0):
        normalized = self._normalize(text)
        topic_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
        keywords = self._extract_keywords(normalized)
        text_preview = text[:500] if len(text) > 500 else text
        
        try:
            self.conn.execute("""
                INSERT OR IGNORE INTO topics 
                (topic_hash, topic_text, normalized_text, keywords, post_type, cycle_number)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (topic_hash, text_preview, normalized, keywords, post_type, cycle_num))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error recording topic: {e}")
    
    def is_too_similar(self, text: str, days_window: int = 7, similarity_threshold: float = 0.6) -> Tuple[bool, str]:
        normalized = self._normalize(text)
        topic_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
        
        cursor = self.conn.execute("""
            SELECT topic_text, created_at FROM topics WHERE topic_hash = ? AND created_at > ?
            ORDER BY created_at DESC LIMIT 1
        """, (topic_hash, datetime.now() - timedelta(days=days_window)))
        
        exact_match = cursor.fetchone()
        if exact_match:
            return True, f"Exact duplicate of post from {exact_match['created_at']}"
        
        input_keywords = set(self._extract_keywords(normalized).split())
        if len(input_keywords) < 3:
            return False, ""
        
        cursor = self.conn.execute("""
            SELECT topic_text, normalized_text, keywords, created_at FROM topics 
            WHERE created_at > ? ORDER BY created_at DESC LIMIT 30
        """, (datetime.now() - timedelta(days=days_window),))
        
        recent_posts = cursor.fetchall()
        best_match_score = 0
        best_match_info = None
        
        for post in recent_posts:
            post_keywords = set(post['keywords'].split()) if post['keywords'] else set()
            if not post_keywords:
                continue
            
            intersection = input_keywords & post_keywords
            union = input_keywords | post_keywords
            jaccard = len(intersection) / len(union) if union else 0
            
            if jaccard > best_match_score:
                best_match_score = jaccard
                best_match_info = (post['topic_text'], post['created_at'])
        
        if best_match_score >= similarity_threshold:
            return True, f"Too similar ({best_match_score:.0%}) to post from {best_match_info[1]}"
        
        return False, ""
    
    def get_recent_topics(self, limit: int = 10, hours: int = 48) -> List[Dict]:
        cursor = self.conn.execute("""
            SELECT topic_text, post_type, created_at FROM topics 
            WHERE created_at > ? ORDER BY created_at DESC LIMIT ?
        """, (datetime.now() - timedelta(hours=hours), limit))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_recent_topics_as_text(self, limit: int = 5) -> str:
        topics = self.get_recent_topics(limit)
        if not topics:
            return "(no recent topics)"
        lines = []
        for i, t in enumerate(topics, 1):
            preview = t['topic_text'][:100] + "..." if len(t['topic_text']) > 100 else t['topic_text']
            lines.append(f"- {preview}")
        return "\n".join(lines)
    
    def count_today(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM topics WHERE date(created_at) = date('now')")
        return cursor.fetchone()['cnt']
    
    def cleanup_old(self, days: int = 30):
        result = self.conn.execute("DELETE FROM topics WHERE created_at < ?", (datetime.now() - timedelta(days=days),))
        self.conn.commit()
        if result.rowcount > 0:
            logger.info(f"Cleaned up {result.rowcount} old topic records")
    
    def _normalize(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _extract_keywords(self, normalized_text: str) -> str:
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
            'she', 'we', 'they', 'what', 'which', 'who', 'when', 'where', 'why',
            'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
            'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
            'than', 'too', 'very', 'just', 'also', 'about', 'into', 'through',
            'during', 'before', 'after', 'above', 'below', 'between', 'under',
            'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'y', 'o',
            'pero', 'en', 'por', 'para', 'con', 'sin', 'sobre', 'desde', 'hasta',
            'es', 'son', 'fue', 'fueron', 'ser', 'estar', 'tengo', 'tiene', 'han',
            'que', 'como', 'muy', 'mucho', 'todo', 'esta', 'este', 'estos'
        }
        words = normalized_text.split()
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return " ".join(keywords[:20])
    
    def close(self):
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

