import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

class ArchiveKeeper:
    def __init__(self, agent):
        self.agent = agent
        self.archive_dir = Path("data/archive")
        self.archive_dir.mkdir(exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_file = self.archive_dir / f"session_{self.session_id}.jsonl"

    def log_event(self, event_type: str, payload: Dict[str, Any]):
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "agent_version": str(self.agent.version),
            "event_type": event_type,
            "data": payload,
            "hash": self._compute_hash(payload)
        }
        with open(self.current_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _compute_hash(self, data: Dict) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
