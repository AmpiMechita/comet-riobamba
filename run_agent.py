import sys
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
