import json
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.agent import COMETRiobambaAgent


def main():
    agent = COMETRiobambaAgent()

    cascade = getattr(agent, "model_cascade", None)
    health = {
        "timestamp": datetime.now().isoformat(),
        "providers": [],
    }

    if cascade and hasattr(cascade, "get_provider_health"):
        try:
            health["providers"] = cascade.get_provider_health()
        except Exception as e:
            health["error"] = f"Error obteniendo health de providers: {e}"
    else:
        health["error"] = "model_cascade no disponible o sin get_provider_health()"

    print(json.dumps(health, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()