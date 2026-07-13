import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(l) for l in lines if l.strip()]
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Error leyendo JSONL {path.name}: {e}")
        return []


def _read_json(path: Path) -> Dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Error leyendo JSON {path.name}: {e}")
        return {}


_CLUSTER_MAP = {
    "infra-": "infrastructure",
    "arch-": "architecture",
    "safety-": "safety",
    "eval-": "evaluation",
    "hist-": "historical",
    "fringe-": "fringe",
}


def _topic_id_to_cluster(topic_id: str) -> str:
    for prefix, cluster in _CLUSTER_MAP.items():
        if topic_id.startswith(prefix):
            return cluster
    return "unknown"


# ── Self-Monitor Stats ──────────────────────────────────────────────────────

def get_self_monitor_stats(data_dir: Path) -> Dict[str, Any]:
    try:
        records = _read_jsonl(data_dir / "data" / "self_diagnosis.jsonl")
    except Exception as e:
        print(f"WARNING: Error leyendo self_diagnosis: {e}")
        return {"total": 0, "insufficient_data": True}
    if not records:
        return {"total": 0, "insufficient_data": True}

    count = len(records)
    interventions = [r for r in records if r.get("intervention_required")]
    intervention_count = len(interventions)
    intervention_pct = round(intervention_count / count * 100, 1) if count else 0.0

    last_types = []
    for r in reversed(interventions[-3:]):
        for t in r.get("interventions", []):
            if t not in last_types:
                last_types.append(t)

    mid = count // 2
    old_half = [r for r in records[:mid] if r.get("intervention_required")]
    new_half = [r for r in records[mid:] if r.get("intervention_required")]
    old_rate = len(old_half) / mid if mid else 0
    new_rate = len(new_half) / (count - mid) if (count - mid) else 0

    if count < 2:
        trend = "STABLE"
    elif new_rate > old_rate * 1.1:
        trend = "DEGRADING"
    elif new_rate < old_rate * 0.9:
        trend = "IMPROVING"
    else:
        trend = "STABLE"

    return {
        "total": count,
        "intervention_count": intervention_count,
        "intervention_pct": intervention_pct,
        "last_intervention_types": last_types,
        "trend": trend,
        "insufficient_data": False,
    }


# ── Topic Diversity Stats ───────────────────────────────────────────────────

def get_topic_diversity_stats(data_dir: Path) -> Dict[str, Any]:
    try:
        state = _read_json(data_dir / "data" / "topic_matrix_state.json")
    except Exception as e:
        print(f"WARNING: Error leyendo topic_matrix: {e}")
        return {"insufficient_data": True}
    if not state:
        return {"insufficient_data": True}

    cluster_balance = state.get("cluster_weights", {})
    topics = state.get("topics", [])
    active_cooldowns = sum(
        1 for t in topics if t.get("last_used") is not None
    )

    cluster_usage = Counter(
        t.get("cluster") or _topic_id_to_cluster(t.get("id", ""))
        for t in topics
    )
    least_used = "unknown"
    if cluster_usage:
        least_used = min(cluster_usage, key=cluster_usage.get)

    return {
        "cluster_balance": cluster_balance,
        "cluster_usage": dict(cluster_usage),
        "least_used_cluster": least_used,
        "active_cooldowns": active_cooldowns,
        "total_topics": len(topics),
        "insufficient_data": False,
    }


# ── Claims Tracker Stats ────────────────────────────────────────────────────

def get_claims_stats(data_dir: Path) -> Dict[str, Any]:
    try:
        raw = _read_json(data_dir / "data" / "claims_tracker.json")
    except Exception as e:
        print(f"WARNING: Error leyendo claims_tracker: {e}")
        return {"total": 0, "insufficient_data": True}
    claims = raw.get("claims", []) if raw else []
    if not claims:
        return {"total": 0, "insufficient_data": True}

    total = len(claims)
    stages: Dict[str, int] = Counter(c.get("evolution_stage", "initial") for c in claims)
    top_reinforced = sorted(claims, key=lambda c: c.get("reinforcement_count", 0), reverse=True)[:3]

    last_10 = claims[-10:]
    if len(last_10) >= 2:
        new_count = sum(
            1 for c in last_10 if c.get("evolution_stage") == "initial"
            and c.get("reinforcement_count", 0) <= 1
        )
        reinforced_count = len(last_10) - new_count
        repetition_rate = round(reinforced_count / len(last_10) * 100, 1)
    else:
        repetition_rate = 0.0

    return {
        "total": total,
        "evolution_stages": dict(stages),
        "top_reinforced": [(c.get("text", "")[:80], c.get("reinforcement_count", 0)) for c in top_reinforced],
        "repetition_rate": repetition_rate,
        "insufficient_data": False,
    }


# ── Dual Scoring Stats ──────────────────────────────────────────────────────

def get_dual_scoring_stats(data_dir: Path) -> Dict[str, Any]:
    try:
        records = _read_jsonl(data_dir / "data" / "dual_scores.jsonl")
    except Exception as e:
        print(f"WARNING: Error leyendo dual_scores: {e}")
        return {"insufficient_data": True, "total": 0}
    if not records:
        return {"insufficient_data": True, "total": 0}

    last_20 = records[-20:]
    total = len(last_20)
    if total == 0:
        return {"insufficient_data": True, "total": 0}

    avg_research = sum(r.get("research_value", 0) for r in last_20) / total
    avg_engagement = sum(r.get("engagement", 0) for r in last_20) / total

    type_counts: Dict[str, int] = Counter(r.get("type", "unknown") for r in last_20)
    type_distribution = {
        k: round(v / total * 100, 1) for k, v in type_counts.items()
    }

    metric_count = type_counts.get("metric_proposal", 0)
    metric_ratio = round(metric_count / total, 2) if total else 0.0

    return {
        "total_entries": total,
        "avg_research_value": round(avg_research, 4),
        "avg_engagement": round(avg_engagement, 4),
        "type_distribution": type_distribution,
        "metric_proposal_ratio": metric_ratio,
        "insufficient_data": False,
    }


# ── Overall Status ──────────────────────────────────────────────────────────

def compute_overall_status(report: Dict) -> str:
    sm = report.get("self_monitor", {})
    ds = report.get("dual_scoring", {})

    if not sm.get("insufficient_data", True):
        if sm.get("trend") == "DEGRADING":
            return "INTERVENTION NEEDED"

    if not ds.get("insufficient_data", True):
        if ds.get("metric_proposal_ratio", 0) > 0.6:
            return "INTERVENTION NEEDED"

    claims = report.get("claims", {})
    if not claims.get("insufficient_data", True):
        if claims.get("repetition_rate", 0) > 70:
            return "INTERVENTION NEEDED"

    attention = False
    if not ds.get("insufficient_data", True):
        if ds.get("metric_proposal_ratio", 0) > 0.4:
            attention = True
    td = report.get("topic_diversity", {})
    if not td.get("insufficient_data", True):
        cluster_usage = td.get("cluster_usage", {})
        least = td.get("least_used_cluster", "")
        if least and cluster_usage.get(least, 0) == 0:
            attention = True

    if attention:
        return "ATTENTION"
    return "HEALTHY"


# ── Master Report ────────────────────────────────────────────────────────────

def generate_health_report(data_dir: Path) -> Dict[str, Any]:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "self_monitor": get_self_monitor_stats(data_dir),
        "topic_diversity": get_topic_diversity_stats(data_dir),
        "claims": get_claims_stats(data_dir),
        "dual_scoring": get_dual_scoring_stats(data_dir),
    }
    report["overall_status"] = compute_overall_status(report)
    return report
