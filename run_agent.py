import sys

# Inicializar QuotaManager
from services.quota_manager import QuotaManager
quota_manager = QuotaManager("config/provider_quotas.json")
from services.quota_manager import set_global_quota_manager
set_global_quota_manager(quota_manager)
print(f"✅ QuotaManager initialized: {quota_manager.get_status()}")
import asyncio
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(override=True)

from utils.logging_config import setup_logging
from config.config import bootstrap_directories

bootstrap_directories()
setup_logging()

from config.credentials import Credentials
from config.config import get_banner
from core.agent import main
from services.karma_updater import update_all_karma
from services.karma_roi_tracker import get_roi_summary


if __name__ == "__main__":
    credentials = Credentials.from_env()
    print(get_banner())
    try:
        asyncio.run(main(credentials))
    except KeyboardInterrupt:
        print("\nInterrupcion manual. Saliendo...")
    except Exception as exc:
        print(f"\nError fatal: {exc}", file=sys.stderr)
        sys.exit(1)


