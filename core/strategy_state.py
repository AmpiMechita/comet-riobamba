import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_STATE: Dict[str, Any] = {
    "top_topics": [],
    "avoid_topics": [],
    "best_tone": "neutral",
    "last_updated": None,
}


def get_default_state() -> Dict[str, Any]:
    return dict(_DEFAULT_STATE)


class StrategyState:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else Path("data/strategy_state.json")

    def load(self) -> Dict[str, Any]:
        if not self._path.exists():
            logger.info("StrategyState: %s no existe, retornando estado por defecto", self._path)
            return get_default_state()
        try:
            with open(self._path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            validated = get_default_state()
            validated.update(data)
            return validated
        except Exception as exc:
            logger.warning("StrategyState: error leyendo %s: %s", self._path, exc)
            return get_default_state()

    def save(self, state: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".tmp",
            prefix="strategy_state_",
            dir=str(self._path.parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
