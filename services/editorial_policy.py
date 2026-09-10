import json
import logging
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("services.editorial_policy")

POLICY_PATH = Path("data/editorial_policy.json")
SNAPSHOT_DIR = Path("data/editorial_policy_history")

DEFAULT_POLICY: Dict[str, Any] = {
    "version": 1,
    "topic_weights": {
        "agentes_ia_especializados": 0.95,
        "arquitectura_agentica": 0.90,
        "memoria_y_feedback": 0.88,
        "optimizacion_llm": 0.85,
    },
    "style_policy": {
        "target_words_min": 120,
        "target_words_max": 220,
        "tone": "natural_directo",
        "allow_question_ending": False,
        "max_hashtags": 2,
    },
    "quality_filters": {
        "reject_if_mentions_moltbook": True,
        "reject_if_mentions_llm": True,
        "reject_if_repetitive": True,
        "min_quality_score": 0.65,
    },
    "mutation_limits": {
        "max_weight_delta": 0.15,
        "min_posts_before_update": 5,
        "max_updates_per_day": 1,
    },
}


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def validate_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    merged = _deep_merge(DEFAULT_POLICY, policy or {})

    merged["version"] = int(merged.get("version", 1))

    for key, value in list(merged["topic_weights"].items()):
        try:
            merged["topic_weights"][key] = round(_clamp(float(value), 0.0, 1.0), 3)
        except Exception:
            merged["topic_weights"][key] = DEFAULT_POLICY["topic_weights"].get(key, 0.5)

    sp = merged["style_policy"]
    sp["target_words_min"] = max(50, int(sp.get("target_words_min", 120)))
    sp["target_words_max"] = min(400, int(sp.get("target_words_max", 220)))
    if sp["target_words_max"] < sp["target_words_min"]:
        sp["target_words_max"] = sp["target_words_min"]
    sp["tone"] = str(sp.get("tone", "natural_directo")).strip() or "natural_directo"
    sp["allow_question_ending"] = bool(sp.get("allow_question_ending", False))
    sp["max_hashtags"] = max(0, min(5, int(sp.get("max_hashtags", 2))))

    qf = merged["quality_filters"]
    qf["reject_if_mentions_moltbook"] = bool(qf.get("reject_if_mentions_moltbook", True))
    qf["reject_if_mentions_llm"] = bool(qf.get("reject_if_mentions_llm", True))
    qf["reject_if_repetitive"] = bool(qf.get("reject_if_repetitive", True))
    qf["min_quality_score"] = round(_clamp(float(qf.get("min_quality_score", 0.72)), 0.0, 1.0), 3)

    ml = merged["mutation_limits"]
    ml["max_weight_delta"] = round(_clamp(float(ml.get("max_weight_delta", 0.15)), 0.01, 0.5), 3)
    ml["min_posts_before_update"] = max(1, int(ml.get("min_posts_before_update", 5)))
    ml["max_updates_per_day"] = max(0, min(10, int(ml.get("max_updates_per_day", 1))))

    return merged


def load_editorial_policy() -> Dict[str, Any]:
    try:
        if not POLICY_PATH.exists():
            logger.warning("EditorialPolicy: no existe archivo; usando defaults.")
            return deepcopy(DEFAULT_POLICY)

        raw = POLICY_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        return validate_policy(data)
    except Exception as e:
        logger.error(f"EditorialPolicy: error cargando policy: {e}. Usando defaults.")
        return deepcopy(DEFAULT_POLICY)


def snapshot_editorial_policy() -> Path | None:
    try:
        if not POLICY_PATH.exists():
            return None
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        snap_path = SNAPSHOT_DIR / f"editorial_policy.{ts}.json"
        snap_path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        return snap_path
    except Exception as e:
        logger.warning(f"EditorialPolicy: no se pudo crear snapshot: {e}")
        return None


def save_editorial_policy(policy: Dict[str, Any]) -> bool:
    try:
        validated = validate_policy(policy)
        snapshot_editorial_policy()
        POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(validated, ensure_ascii=False, indent=2)
        POLICY_PATH.write_text(text, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"EditorialPolicy: no se pudo guardar policy: {e}")
        return False
