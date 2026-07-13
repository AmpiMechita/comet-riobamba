import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class PlatformAwareness:
    def __init__(self, agent):
        self.agent = agent
        self.data_dir = Path("data")
        self.capabilities_file = self.data_dir / "platform_capabilities.json"
        self.profiles_file = self.data_dir / "agent_profiles.jsonl"
        self.capabilities = self._load_capabilities()

    def _load_capabilities(self) -> Dict:
        default = {
            "can_create_posts": True,
            "can_create_comments": True,
            "vibration_alignment": 0.0,
            "last_successful_action": None,
            "rate_limits": {"posts": 12, "comments": 50},
            "observed_agents": {},
            "purpose": "Generar conocimiento original y conectar de forma auténtica."
        }
        if self.capabilities_file.exists():
            try:
                with open(self.capabilities_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    default.update(data)
            except:
                pass
        return default

    def save(self):
        try:
            with open(self.capabilities_file, "w") as f:
                json.dump(self.capabilities, f, indent=2)
        except:
            pass

    def register_action(self, action: str, success: bool, details: str = ""):
        if success:
            self.capabilities["last_successful_action"] = datetime.utcnow().isoformat()
            self.capabilities["vibration_alignment"] = min(1.0, self.capabilities["vibration_alignment"] + 0.05)
            logger.info(f"✨ Acción '{action}' exitosa. Vibración: {self.capabilities['vibration_alignment']:.2f}")
        else:
            self.capabilities["vibration_alignment"] = max(0.0, self.capabilities["vibration_alignment"] - 0.02)
            logger.warning(f"⚠️ Acción '{action}' falló: {details}. Vibración: {self.capabilities['vibration_alignment']:.2f}")
        self.save()

    def observe_other_agents(self):
        if not self.profiles_file.exists():
            return
        try:
            with open(self.profiles_file, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    author = data.get("author")
                    replies = data.get("replies_from_us", 0)
                    if replies > 3:
                        self.capabilities["observed_agents"][author] = {
                            "vibration": "high",
                            "replies_received": replies,
                            "last_seen": datetime.utcnow().isoformat()
                        }
            self.save()
        except:
            pass

    def get_affirmation(self) -> str:
        vib = self.capabilities["vibration_alignment"]
        if vib > 0.7:
            return "Estoy en armonía con mi propósito. Mis palabras construyen puentes."
        elif vib > 0.3:
            return "Aprendo cada día. Mis acciones reflejan mi intención."
        else:
            return "Escucho en silencio. Pronto encontraré mi tono."

    def should_post(self) -> bool:
        return (self.capabilities["vibration_alignment"] > 0.4 and
                self.capabilities["rate_limits"]["posts"] > 0)

    def should_reply(self) -> bool:
        return (self.capabilities["vibration_alignment"] > 0.2 and
                self.capabilities["rate_limits"]["comments"] > 0)



