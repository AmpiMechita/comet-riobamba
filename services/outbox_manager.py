import asyncio
import sqlite3
import pathlib
import json
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from enum import Enum

from config import OUTBOX_DB_PATH

logger = logging.getLogger(__name__)


class OutboxStatus(Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    ABANDONED = "abandoned"


class OutboxManager:
    def __init__(self, cfg=None, db_path=None):
        self.cfg = cfg or {}
        self.db_path = db_path or OUTBOX_DB_PATH
        self.conn = self._get_connection()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(pathlib.Path(self.db_path).resolve()))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                submolt TEXT,
                post_type TEXT DEFAULT 'original',
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                published_at TIMESTAMP,
                last_error TEXT,
                payload_json TEXT,
                priority INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_outbox_priority ON outbox(priority DESC, created_at ASC)")
        self.conn.commit()

    def enqueue(self, title: str, content: str, submolt: str = None,
                post_type: str = "original", priority: int = 0) -> int:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO outbox (title, content, submolt, post_type, status, priority, payload_json)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """, (title, content, submolt, post_type, priority, json.dumps({"title": title, "content": content, "submolt": submolt})))
        self.conn.commit()
        item_id = cursor.lastrowid
        logger.info(f"Enqueued outbox item #{item_id}")
        return item_id

    def get_pending_items(self, limit: int = 10) -> List[Dict]:
        cursor = self.conn.execute("""
            SELECT * FROM outbox WHERE status = 'pending' AND attempts < max_attempts
            ORDER BY priority DESC, created_at ASC LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def mark_publishing(self, item_id: int):
        self.conn.execute("UPDATE outbox SET status = 'publishing', attempts = attempts + 1 WHERE id = ?", (item_id,))
        self.conn.commit()

    def mark_published(self, item_id: int):
        self.conn.execute("UPDATE outbox SET status = 'published', published_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
        self.conn.commit()

    def mark_failed(self, item_id: int, error: str = ""):
        item = self.get_by_id(item_id)
        if item and item['attempts'] >= item['max_attempts']:
            status = 'abandoned'
        else:
            status = 'pending'
        self.conn.execute("UPDATE outbox SET status = ?, last_error = ?, attempts = attempts + 1 WHERE id = ?", (status, error, item_id))
        self.conn.commit()

    async def flush(self, publish_func) -> Dict[str, int]:
        results = {'published': 0, 'failed': 0, 'remaining': 0}
        pending = self.get_pending_items(limit=5)
        if not pending:
            return results

        for item in pending:
            self.mark_publishing(item['id'])
            try:
                if asyncio.iscoroutinefunction(publish_func):
                    result = await publish_func(item['title'], item['content'], item.get('submolt'))
                else:
                    result = publish_func(item['title'], item['content'], item.get('submolt'))
                if result.get('success'):
                    self.mark_published(item['id'])
                    results['published'] += 1
                else:
                    self.mark_failed(item['id'], result.get('error'))
                    results['failed'] += 1
            except Exception as e:
                self.mark_failed(item['id'], str(e))
                results['failed'] += 1

        remaining_cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM outbox WHERE status = 'pending'")
        results['remaining'] = remaining_cursor.fetchone()['cnt']
        return results

    def get_by_id(self, item_id: int) -> Optional[Dict]:
        cursor = self.conn.execute("SELECT * FROM outbox WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_stats(self) -> Dict[str, int]:
        cursor = self.conn.execute("""
            SELECT COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                   COUNT(CASE WHEN status = 'publishing' THEN 1 END) as publishing,
                   COUNT(CASE WHEN status = 'published' THEN 1 END) as published,
                   COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                   COUNT(CASE WHEN status = 'abandoned' THEN 1 END) as abandoned,
                   COUNT(*) as total FROM outbox
        """)
        return dict(cursor.fetchone())

    def cleanup_old(self, days: int = 7):
        result = self.conn.execute("""
            DELETE FROM outbox WHERE status IN ('published', 'abandoned')
            AND created_at < datetime('now', '-' || ? || ' days')
        """, (days,))
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

