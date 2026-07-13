import logging
import json
import random
from typing import Dict, List, Optional
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

class SubmoltDiscovery:
    def __init__(self, data_dir: str = "data"):
        self.submolts: Dict[str, Dict] = {}
        self.popularity: Dict[str, int] = defaultdict(int)
        self.data_file = Path(data_dir) / "submolts_discovery.json"
        self._load_state()

    def _load_state(self):
        try:
            with open(self.data_file, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                self.submolts = data.get("submolts", {})
                self.popularity = defaultdict(int, data.get("popularity", {}))
                logger.info(f"Cargados {len(self.submolts)} submolts")
        except FileNotFoundError:
            logger.info("No hay submolts previos")

    def save_state(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_file, 'w', encoding='utf-8-sig') as f:
            json.dump({"submolts": self.submolts, "popularity": dict(self.popularity)}, f, indent=2)

    def add_from_post(self, post: Dict):
        slug = post.get("submolt")
        name = post.get("submolt_name") or post.get("submolt") or slug
        if not slug:
            return
        if slug not in self.submolts:
            self.submolts[slug] = {"slug": slug, "name": name}
            logger.info(f"Nuevo submolt: {slug} -> {name}")
        self.popularity[slug] += 1

    def get_trending(self, limit=20):
        sorted_items = sorted(self.popularity.items(), key=lambda x: x[1], reverse=True)
        return [self.submolts[s] for s, _ in sorted_items[:limit] if s in self.submolts]

    def get_random(self):
        if not self.submolts:
            return {"slug": "general", "name": "General"}
        candidates = []
        for slug, info in self.submolts.items():
            weight = self.popularity.get(slug, 1)
            candidates.extend([slug] * weight)
        chosen = random.choice(candidates)
        return self.submolts[chosen]

    def select_best_submolt(self, text: str):
        text_lower = text.lower()
        best = None
        best_score = 0
        for slug, info in self.submolts.items():
            name = info.get("name", "").lower()
            score = sum(1 for word in name.split() if word in text_lower)
            if slug in text_lower:
                score += 1
            if score > best_score:
                best_score = score
                best = info
        if best:
            return best
        trending = self.get_trending(1)
        return trending[0] if trending else self.get_random()
