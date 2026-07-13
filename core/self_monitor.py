import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


class SelfMonitor:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def run_diagnosis(self) -> Dict:
        topic = self._detect_topic_stuck()
        pattern = self._detect_pattern_rigidity()
        metric = self._detect_metric_recycling()

        interventions: List[str] = []
        if topic["stuck"]:
            interventions.append("topic_rotation")
        if pattern["rigid"]:
            interventions.append("pattern_break")
        if metric["recycling"]:
            interventions.append("metric_freshness")

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "topic_stuck": topic,
            "pattern_rigidity": pattern,
            "metric_recycling": metric,
            "intervention_required": len(interventions) > 0,
            "interventions": interventions,
        }

    def _detect_topic_stuck(self) -> Dict:
        posts_file = self.data_dir / "data" / "published_posts.json"
        if not posts_file.exists():
            return {"stuck": False, "dominant_topic": [], "concentration": 0.0}
        try:
            data = json.loads(posts_file.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not data:
                return {"stuck": False, "dominant_topic": [], "concentration": 0.0}

            topics = [entry.get("topic", "") for entry in data[-15:] if isinstance(entry, dict)]
            if len(topics) < 2:
                return {"stuck": False, "dominant_topic": [], "concentration": 0.0}

            similarities = []
            for i in range(len(topics) - 1):
                a = set(topics[i].lower().split())
                b = set(topics[i + 1].lower().split())
                if not a or not b:
                    continue
                intersection = a & b
                union = a | b
                sim = len(intersection) / len(union)
                similarities.append(sim)

            avg_sim = sum(similarities) / len(similarities) if similarities else 0.0

            all_words = [w for t in topics for w in t.lower().split()]
            word_counts = Counter(all_words)
            stopwords = {
                "the", "a", "an", "in", "of", "to", "for", "and", "is", "on",
                "at", "with", "from", "by", "that", "this", "it", "are", "was",
                "be", "not", "but", "or", "as", "we", "i", "about", "across",
                "after", "all", "also", "am", "been", "being", "can", "do",
                "does", "done", "each", "had", "has", "have", "her", "here",
                "him", "his", "how", "its", "just", "like", "may", "me", "more",
                "most", "much", "my", "no", "nor", "now", "of", "off", "old",
                "once", "only", "other", "our", "out", "own", "per", "pre",
                "put", "said", "same", "she", "should", "show", "side", "since",
                "some", "still", "such", "than", "them", "then", "there",
                "these", "they", "thing", "too", "under", "upon", "us", "very",
                "was", "way", "were", "what", "when", "where", "which", "while",
                "who", "why", "will", "would", "you", "your",
            }
            dominant = [
                word for word, count in word_counts.most_common(5)
                if word not in stopwords and count >= 2
            ]

            stuck = avg_sim > 0.45
            return {
                "stuck": stuck,
                "dominant_topic": dominant[:3],
                "concentration": round(avg_sim, 3),
            }
        except Exception:
            return {"stuck": False, "dominant_topic": [], "concentration": 0.0}

    def _detect_pattern_rigidity(self) -> Dict:
        traces_dir = self.data_dir / "traces"
        if not traces_dir.exists():
            return {"rigid": False, "entropy": 1.0, "dominant_openers": []}

        contents: List[str] = []
        try:
            files = sorted(traces_dir.glob("phase_b_*.jsonl"), reverse=True)
            for f in files:
                if len(contents) >= 30:
                    break
                for line in f.read_text(encoding="utf-8").strip().splitlines():
                    if len(contents) >= 30:
                        break
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("span") == "llm_generation":
                            text = record.get("content") or record.get("text") or ""
                            if text:
                                contents.append(text)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass

        if not contents:
            return {"rigid": False, "entropy": 1.0, "dominant_openers": []}

        openers: List[str] = []
        for text in contents:
            first_sentence = text.split(".")[0].strip() if text else ""
            if first_sentence:
                words = first_sentence.split()[:3]
                if words:
                    opener = " ".join(words).lower().rstrip(",.!?:;")
                    openers.append(opener)

        if not openers:
            return {"rigid": False, "entropy": 1.0, "dominant_openers": []}

        opener_counts = Counter(openers)
        total = len(openers)

        entropy = 0.0
        for count in opener_counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        unique = len(opener_counts)
        if unique <= 1:
            normalized_entropy = 0.0
        else:
            max_entropy = math.log2(unique)
            normalized_entropy = entropy / max_entropy

        dominant = [opener for opener, _ in opener_counts.most_common(3)]

        return {
            "rigid": normalized_entropy < 0.5,
            "entropy": round(normalized_entropy, 3),
            "dominant_openers": dominant,
        }

    def _detect_metric_recycling(self) -> Dict:
        patterns = [
            (r"\d+%", "percentage"),
            (r"\d+ms", "milliseconds"),
            (r"\d+\.?\d*\s*(?:percentile|pct|p)\s*", "percentile"),
            (r"9\d{2,3}ms", "high_latency"),
            (r"95th\s*percentile", "p95"),
            (r"99th\s*percentile", "p99"),
        ]

        texts: List[str] = []

        posts_file = self.data_dir / "data" / "published_posts.json"
        if posts_file.exists():
            try:
                data = json.loads(posts_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for entry in data[-20:]:
                        topic = entry.get("topic", "") if isinstance(entry, dict) else ""
                        if topic:
                            texts.append(topic)
            except Exception:
                pass

        traces_dir = self.data_dir / "traces"
        if traces_dir.exists():
            try:
                files = sorted(traces_dir.glob("phase_b_*.jsonl"), reverse=True)
                for f in files[:3]:
                    for line in f.read_text(encoding="utf-8").strip().splitlines():
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if record.get("span") == "llm_generation":
                                text = record.get("content") or record.get("text") or ""
                                if text:
                                    texts.append(text)
                        except (json.JSONDecodeError, KeyError):
                            continue
            except Exception:
                pass

        all_text = " ".join(texts)

        metric_counts: Dict[str, int] = {}
        for pattern, label in patterns:
            matches = re.findall(pattern, all_text, re.IGNORECASE)
            if len(matches) >= 3:
                metric_counts[label] = len(matches)

        repeated_metrics = [label for label, count in metric_counts.items() if count >= 3]

        return {
            "recycling": len(repeated_metrics) >= 3,
            "repeated_metrics": repeated_metrics,
        }
