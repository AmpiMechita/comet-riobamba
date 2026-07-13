import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class AutoOptimizer:
    def __init__(self, agent):
        self.agent = agent
        self.data_dir = Path("data")
        self.events_path = self.data_dir / "comment_events.jsonl"
        self.candidates_path = self.data_dir / "improvement_candidates.jsonl"

    def analyze_and_propose(self):
        proposals = []
        exception_count = self._count_exceptions_last_hours(24)
        if exception_count > 5:
            proposals.append({
                "type": "config_change",
                "parameter": "max_phase_c_replies_per_cycle",
                "current": self.agent.max_phase_c_replies_per_cycle,
                "suggested": max(1, self.agent.max_phase_c_replies_per_cycle - 1),
                "reason": f"Demasiados errores ({exception_count}) en últimas 24h."
            })
        self._save_proposals(proposals)

    def _count_exceptions_last_hours(self, hours: int) -> int:
        if not self.events_path.exists():
            return 0
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        count = 0
        try:
            with open(self.events_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("event_type") == "comment_reply_exception":
                        ts = datetime.fromisoformat(event["timestamp_utc"].replace('Z', '+00:00'))
                        if ts > cutoff:
                            count += 1
        except Exception as e:
            logger.warning(f"Error contando excepciones: {e}")
        return count

    def _save_proposals(self, proposals):
        for p in proposals:
            record = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "source": "auto_optimizer",
                "proposal": p
            }
            with open(self.candidates_path, "a", encoding="utf-8-sig") as f:
                f.write(json.dumps(record) + "\n")
        if proposals:
            logger.info(f"AutoOptimizer generó {len(proposals)} propuestas.")

