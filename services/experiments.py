"""Minimal experiment framework for prompt/model A/B testing."""

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENTS_PATH = Path("data/experiments.json")


def load_experiments(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or DEFAULT_EXPERIMENTS_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Experiments: error cargando %s: %s", p, e)
        return {}


def pick_variant(experiment_key: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    cfg = config or load_experiments()
    exp = cfg.get(experiment_key)
    if not exp or not exp.get("enabled"):
        return None
    variants = exp.get("variants", [])
    if not variants:
        return None
    weights = [v.get("weight", 1) for v in variants]
    chosen = random.choices(variants, weights=weights, k=1)[0]
    return chosen["id"]


def get_variant_config(experiment_key: str, variant_id: str,
                       config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_experiments()
    exp = cfg.get(experiment_key, {})
    for v in exp.get("variants", []):
        if v["id"] == variant_id:
            return v
    return {}


# ── A/B Testing with Statistical Analysis ────────────────────────────────

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

EXPERIMENT_RESULTS_DIR = Path("data/experiment_results")


@dataclass
class VariantResult:
    """Single observation for a variant."""
    variant_id: str
    metric_value: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


def record_result(
    experiment_key: str,
    variant_id: str,
    metric_value: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a single metric observation for a variant.

    Call this after a post/reply is published and its outcome is measured.
    """
    EXPERIMENT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = EXPERIMENT_RESULTS_DIR / f"{experiment_key}.jsonl"
    record = {
        "variant_id": variant_id,
        "metric_value": metric_value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    try:
        with open(results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Experiments: failed to record result for %s: %s", experiment_key, e)


def load_results(experiment_key: str) -> Dict[str, List[float]]:
    """Load all results for an experiment, grouped by variant.

    Returns: {"variant_a": [1.2, 0.8, ...], "variant_b": [0.9, 1.1, ...]}
    """
    results_file = EXPERIMENT_RESULTS_DIR / f"{experiment_key}.jsonl"
    if not results_file.exists():
        return {}

    by_variant: Dict[str, List[float]] = {}
    try:
        with open(results_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    vid = record["variant_id"]
                    val = record["metric_value"]
                    by_variant.setdefault(vid, []).append(val)
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        logger.warning("Experiments: failed to load results for %s: %s", experiment_key, e)

    return by_variant


def _normal_cdf(x: float) -> float:
    """Approximation of the standard normal CDF (Abramowitz and Stegun)."""
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2.0)
    return 0.5 * (1.0 + sign * y)


def welch_t_test(values_a: List[float], values_b: List[float]) -> Dict[str, Any]:
    """Welch's t-test for two independent samples (unequal variance).

    Returns: {"t_stat": float, "p_value_approx": float, "significant": bool,
              "mean_a": float, "mean_b": float, "n_a": int, "n_b": int}
    """
    n_a, n_b = len(values_a), len(values_b)
    if n_a < 2 or n_b < 2:
        return {
            "t_stat": 0.0, "p_value_approx": 1.0, "significant": False,
            "mean_a": 0.0, "mean_b": 0.0, "n_a": n_a, "n_b": n_b,
        }

    mean_a = sum(values_a) / n_a
    mean_b = sum(values_b) / n_b
    var_a = sum((x - mean_a) ** 2 for x in values_a) / (n_a - 1)
    var_b = sum((x - mean_b) ** 2 for x in values_b) / (n_b - 1)

    se_sq = var_a / n_a + var_b / n_b
    se = math.sqrt(se_sq) if se_sq > 0 else 1e-10
    t_stat = (mean_a - mean_b) / se

    # Approximate p-value using normal distribution (good for n > 20)
    z = abs(t_stat)
    p_value = 2.0 * (1.0 - _normal_cdf(z))

    return {
        "t_stat": round(t_stat, 4),
        "p_value_approx": round(p_value, 6),
        "significant": p_value < 0.05,
        "mean_a": round(mean_a, 4),
        "mean_b": round(mean_b, 4),
        "n_a": n_a,
        "n_b": n_b,
    }


def analyze_experiment(experiment_key: str) -> Dict[str, Any]:
    """Analyze an experiment's results and determine if there's a winner.

    Returns a summary with statistical significance for each pair of variants.
    """
    results = load_results(experiment_key)
    if len(results) < 2:
        return {
            "experiment": experiment_key,
            "status": "insufficient_variants",
            "variants": list(results.keys()),
            "total_observations": sum(len(v) for v in results.values()),
        }

    variants = sorted(results.keys())
    comparisons = []
    winner = None
    best_mean = -float("inf")

    for vid, vals in results.items():
        mean = sum(vals) / len(vals) if vals else 0
        if mean > best_mean:
            best_mean = mean
            winner = vid

    # Pairwise comparisons
    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            va, vb = variants[i], variants[j]
            test = welch_t_test(results[va], results[vb])
            comparisons.append({
                "variant_a": va,
                "variant_b": vb,
                **test,
            })

    any_significant = any(c["significant"] for c in comparisons)

    return {
        "experiment": experiment_key,
        "status": "significant" if any_significant else "inconclusive",
        "winner": winner if any_significant else None,
        "variants": {
            vid: {"n": len(vals), "mean": round(sum(vals) / len(vals), 4) if vals else 0}
            for vid, vals in results.items()
        },
        "comparisons": comparisons,
        "total_observations": sum(len(v) for v in results.values()),
    }
