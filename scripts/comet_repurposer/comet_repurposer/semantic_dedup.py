"""
Semantic deduplication.

Detects when two source items cover the same topic even if their text
is different. Two strategies, used in cascade:

  Strategy 1 — Embeddings (preferred when an embedding API is available)
    Uses Groq's free ``text-embedding-3-small``-style endpoint, or any
    OpenAI-compatible embeddings endpoint. Stores vectors in SQLite.

  Strategy 2 — Lexical Jaccard fallback (always available, no API)
    Tokenizes the body, removes stopwords, computes Jaccard similarity
    against previously-seen items. Crude but catches the "circuit breaker
    x4 in a week" problem without spending any API quota.

Both strategies write to the same SQLite table ``semantic_dedup`` so the
two modes can coexist: embeddings for high confidence, lexical for the
baseline.

Usage in pipeline::

    sd = SemanticDedup(cfg.semantic_dedup_db_path,
                       embeddings_client=embed_client,  # or None
                       threshold=0.85)
    if sd.is_duplicate(item, seen_items):
        # skip
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import requests


# ---------------------------------------------------------------------------
# Stopwords (small English + Spanish set — no external dependency)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    # English
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "from", "up", "down", "out", "off", "over", "under", "again",
    "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "them", "their", "his", "her", "its", "our", "your",
    "what", "which", "who", "when", "where", "why", "how", "all",
    "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "not", "only", "own", "same", "so", "than", "too",
    "very", "can", "will", "just", "should", "now",
    # Spanish
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o",
    "pero", "porque", "mientras", "cuando", "de", "del", "al", "en",
    "con", "por", "para", "sin", "sobre", "entre", "hasta", "es", "son",
    "era", "fueron", "ser", "estar", "este", "esta", "estos", "estas",
    "eso", "esa", "eso", "esto", "que", "como", "cual", "quien",
    "donde", "cuando", "todo", "todos", "toda", "todas", "más", "menos",
    "muy", "también", "solo", "ya", "ha", "han", "fue", "son",
}


_TOKEN_RE = re.compile(r"\b[a-záéíóúüñ][a-záéíóúüñ0-9_-]{1,}\b", re.IGNORECASE)


def tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, remove stopwords, return tokens."""
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    """Jaccard similarity between two token sequences."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def cosine(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Cosine similarity between two numeric vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


# ---------------------------------------------------------------------------
# Lightweight TF-IDF (no external dependency, no API calls)
# ---------------------------------------------------------------------------

class TfidfIndex:
    """In-memory TF-IDF index over a corpus.

    Better than Jaccard for technical writing because:
      - Common technical words ("circuit", "breaker", "token", "throttling")
        get weighted by how rare they are across the corpus.
      - "the", "a", etc. already filtered as stopwords.
      - Cosine similarity over TF-IDF captures topical overlap even when
        exact wording differs.

    Usage::

        idx = TfidfIndex()
        idx.add("doc1", tokens1)
        idx.add("doc2", tokens2)
        sim = idx.similarity("doc1", "doc2")
    """

    def __init__(self) -> None:
        self._docs: dict[str, list[str]] = {}
        self._df: dict[str, int] = {}  # document frequency
        self._dirty = True
        self._idf_cache: dict[str, float] = {}

    def add(self, doc_id: str, tokens: Sequence[str]) -> None:
        self._docs[doc_id] = list(tokens)
        for term in set(tokens):
            self._df[term] = self._df.get(term, 0) + 1
        self._dirty = True

    def _recompute_idf(self) -> None:
        n = len(self._docs) or 1
        self._idf_cache = {
            term: math.log((1 + n) / (1 + df)) + 1.0
            for term, df in self._df.items()
        }
        self._dirty = False

    def _tfidf_vector(self, tokens: Sequence[str]) -> dict[str, float]:
        if self._dirty:
            self._recompute_idf()
        counts: dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        total = len(tokens) or 1
        return {
            term: (count / total) * self._idf_cache.get(term, 1.0)
            for term, count in counts.items()
        }

    def similarity(self, doc_id_a: str, doc_id_b: str) -> float:
        if doc_id_a not in self._docs or doc_id_b not in self._docs:
            return 0.0
        va = self._tfidf_vector(self._docs[doc_id_a])
        vb = self._tfidf_vector(self._docs[doc_id_b])
        if not va or not vb:
            return 0.0
        # Sparse cosine
        common = set(va) & set(vb)
        if not common:
            return 0.0
        dot = sum(va[t] * vb[t] for t in common)
        na = math.sqrt(sum(v * v for v in va.values()))
        nb = math.sqrt(sum(v * v for v in vb.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def similarity_tokens(self, tokens_a: Sequence[str],
                          doc_id_b: str) -> float:
        """Compare a free token sequence against a stored doc."""
        if doc_id_b not in self._docs:
            return 0.0
        va = self._tfidf_vector(tokens_a)
        vb = self._tfidf_vector(self._docs[doc_id_b])
        if not va or not vb:
            return 0.0
        common = set(va) & set(vb)
        if not common:
            return 0.0
        dot = sum(va[t] * vb[t] for t in common)
        na = math.sqrt(sum(v * v for v in va.values()))
        nb = math.sqrt(sum(v * v for v in vb.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


# ---------------------------------------------------------------------------
# Embeddings client (OpenAI-compatible)
# ---------------------------------------------------------------------------

class EmbeddingsClient:
    """Tiny client for OpenAI-compatible ``/embeddings`` endpoints.

    Works with:
      - OpenAI (text-embedding-3-small)
      - Groq (does not have embeddings yet as of 2026-Q2, but if they add it)
      - OpenRouter embeddings passthrough
      - Local Ollama (http://localhost:11434/v1 with nomic-embed-text)
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> List[float]:
        url = self.base_url + "/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {"model": self.model, "input": text[:8000]}
        resp = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"embeddings HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return list(data["data"][0]["embedding"])


# ---------------------------------------------------------------------------
# Semantic dedup store
# ---------------------------------------------------------------------------

@dataclass
class DedupHit:
    """A duplicate hit returned by ``is_duplicate``."""
    source_id: str
    similarity: float
    method: str   # 'embedding' | 'lexical'


class SemanticDedup:
    """SQLite-backed semantic deduplicator.

    Strategy cascade (per pair of items):
      1. Embeddings (cosine) — when an embeddings client is configured
         AND both items have embeddings stored. Highest fidelity.
      2. TF-IDF (cosine over weighted term vectors) — when no embeddings
         available but tokens exist. Captures topical overlap much better
         than Jaccard on technical writing.
      3. Jaccard on token sets — last resort fallback.

    Use as follows::

        sd = SemanticDedup(db_path, embeddings_client=client_or_None)
        sd.register(item.source_id, item.body, item.title)
        hits = sd.find_duplicates(new_item.source_id, new_item.body, threshold=0.85)
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS semantic_dedup (
        source_id TEXT PRIMARY KEY,
        title TEXT,
        tokens TEXT,            -- JSON list of tokens (for lexical/TF-IDF)
        embedding BLOB,         -- JSON list of floats (for embedding mode)
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_created ON semantic_dedup(created_at);
    """

    def __init__(
        self,
        db_path: Path,
        embeddings_client: Optional[EmbeddingsClient] = None,
        max_lexical_items: int = 500,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embeddings_client = embeddings_client
        self.max_lexical_items = max_lexical_items
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()
        # In-memory TF-IDF index, rebuilt lazily from DB on first query.
        self._tfidf = TfidfIndex()
        self._tfidf_loaded = False

    def _load_tfidf_from_db(self) -> None:
        """Populate the in-memory TF-IDF index from stored tokens."""
        if self._tfidf_loaded:
            return
        self._tfidf = TfidfIndex()
        cur = self._conn.execute(
            "SELECT source_id, tokens FROM semantic_dedup "
            "ORDER BY created_at DESC LIMIT ?",
            (self.max_lexical_items,),
        )
        for row in cur.fetchall():
            tokens = json.loads(row[1] or "[]")
            if tokens:
                self._tfidf.add(row[0], tokens)
        self._tfidf_loaded = True

    def register(self, source_id: str, body: str, title: str = "") -> None:
        """Register an item so future items can be compared against it."""
        tokens = tokenize((title + "\n" + body) if title else body)
        embedding: Optional[List[float]] = None
        if self.embeddings_client:
            try:
                embedding = self.embeddings_client.embed(title + "\n" + body)
            except Exception:  # noqa: BLE001
                embedding = None

        self._conn.execute(
            "INSERT OR REPLACE INTO semantic_dedup "
            "(source_id, title, tokens, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                source_id,
                title,
                json.dumps(tokens),
                json.dumps(embedding) if embedding else None,
                time.time(),
            ),
        )
        self._conn.commit()
        # Update in-memory TF-IDF index incrementally.
        if tokens:
            self._tfidf.add(source_id, tokens)
        self._tfidf_loaded = True

    def find_duplicates(
        self,
        source_id: str,
        body: str,
        title: str = "",
        threshold: float = 0.85,
    ) -> List[DedupHit]:
        """Return any registered items whose similarity >= ``threshold``.

        Strategy cascade: embeddings > TF-IDF > Jaccard.
        """
        query_tokens = tokenize((title + "\n" + body) if title else body)
        query_embedding: Optional[List[float]] = None
        if self.embeddings_client:
            try:
                query_embedding = self.embeddings_client.embed(title + "\n" + body)
            except Exception:  # noqa: BLE001
                query_embedding = None

        # Make sure the in-memory TF-IDF index is loaded.
        self._load_tfidf_from_db()

        cur = self._conn.execute(
            "SELECT source_id, tokens, embedding FROM semantic_dedup "
            "WHERE source_id != ? "
            "ORDER BY created_at DESC LIMIT ?",
            (source_id, self.max_lexical_items),
        )
        hits: List[DedupHit] = []
        for row in cur.fetchall():
            other_id = row[0]
            other_tokens = json.loads(row[1] or "[]")
            other_embedding = json.loads(row[2]) if row[2] else None

            # Prefer embedding cosine when both sides have it.
            if query_embedding and other_embedding:
                sim = cosine(query_embedding, other_embedding)
                method = "embedding"
            elif query_tokens and other_tokens:
                # TF-IDF cosine — much better than Jaccard for tech writing.
                sim = self._tfidf.similarity_tokens(query_tokens, other_id)
                method = "tfidf"
                # If TF-IDF gives a weak signal, also try Jaccard as a
                # complementary check; keep the max.
                j_sim = jaccard(query_tokens, other_tokens)
                if j_sim > sim:
                    sim = j_sim
                    method = "lexical"
            else:
                continue

            if sim >= threshold:
                hits.append(DedupHit(
                    source_id=other_id, similarity=round(sim, 3), method=method,
                ))
        hits.sort(key=lambda h: h.similarity, reverse=True)
        return hits

    def is_duplicate(
        self, source_id: str, body: str, title: str = "",
        threshold: float = 0.85,
    ) -> Tuple[bool, Optional[DedupHit]]:
        """Convenience: return (True, hit) if a duplicate exists."""
        hits = self.find_duplicates(source_id, body, title, threshold)
        if hits:
            return True, hits[0]
        return False, None

    def close(self) -> None:
        self._conn.close()
