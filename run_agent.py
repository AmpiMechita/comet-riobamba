import sys
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv()

from config.credentials import Credentials
from config.config import get_banner, bootstrap_directories
from core.agent import main


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )


if __name__ == "__main__":
    bootstrap_directories()
    setup_logging()
    credentials = Credentials.from_env()
    print(get_banner())
    try:
        asyncio.run(main(credentials))
    except KeyboardInterrupt:
        print("\nInterrupción manual. Saliendo...")
    except Exception as exc:
        print(f"\nError fatal: {exc}", file=sys.stderr)
        sys.exit(1)