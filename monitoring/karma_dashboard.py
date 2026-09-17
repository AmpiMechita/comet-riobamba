# monitoring/karma_dashboard.py
"""Dashboard simple de métricas Karma ROI."""

import json
from pathlib import Path
from datetime import datetime, timedelta

KARMA_TRACKER_FILE = Path("data/karma_roi_tracker.jsonl")

def get_dashboard_data(hours: int = 24):
    """Obtiene datos para el dashboard."""
    if not KARMA_TRACKER_FILE.exists():
        return {"error": "No hay datos"}
    
    cutoff = (datetime.now() - timedelta(hours=hours)).timestamp()
    
    entries = []
    with open(KARMA_TRACKER_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    
    # Filtrar por tiempo
    recent = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry["generated_at"].replace("Z", "+00:00")).timestamp()
            if ts >= cutoff:
                recent.append(entry)
        except:
            pass
    
    # Calcular métricas
    phase_a = [e for e in recent if e.get("phase") == "A"]
    phase_b = [e for e in recent if e.get("phase") == "B"]
    
    return {
        "period": f"{hours}h",
        "phase_a": {
            "count": len(phase_a),
            "total_cost": sum(e.get("cost_usd", 0) for e in phase_a),
            "total_karma": sum(e.get("karma_score", 0) for e in phase_a),
            "avg_karma_per_post": sum(e.get("karma_score", 0) for e in phase_a) / len(phase_a) if phase_a else 0,
        },
        "phase_b": {
            "count": len(phase_b),
            "total_cost": sum(e.get("cost_usd", 0) for e in phase_b),
            "total_karma": sum(e.get("karma_score", 0) for e in phase_b),
            "avg_karma_per_comment": sum(e.get("karma_score", 0) for e in phase_b) / len(phase_b) if phase_b else 0,
        },
        "roi_ratio": (
            (sum(e.get("karma_score", 0) for e in phase_a) / sum(e.get("cost_usd", 0) for e in phase_a)) /
            (sum(e.get("karma_score", 0) for e in phase_b) / sum(e.get("cost_usd", 0) for e in phase_b))
            if phase_a and phase_b and sum(e.get("cost_usd", 0) for e in phase_b) > 0
            else 0
        ),
        "top_posts": sorted(phase_a, key=lambda x: x.get("karma_score", 0), reverse=True)[:5],
        "top_comments": sorted(phase_b, key=lambda x: x.get("karma_score", 0), reverse=True)[:5],
    }

def print_dashboard(hours: int = 24):
    """Imprime dashboard en consola."""
    data = get_dashboard_data(hours)
    
    print(f"\n{'='*60}")
    print(f"📊 KARMA ROI DASHBOARD - {data['period']}")
    print(f"{'='*60}")
    
    if "error" in data:
        print(f"❌ {data['error']}")
        return
    
    print(f"\n📝 PHASE A (Posts)")
    print(f"   Count: {data['phase_a']['count']}")
    print(f"   Costo: ${data['phase_a']['total_cost']:.6f} USD")
    print(f"   Karma: {data['phase_a']['total_karma']}")
    print(f"   Avg: {data['phase_a']['avg_karma_per_post']:.2f} karma/post")
    
    print(f"\n💬 PHASE B (Comments)")
    print(f"   Count: {data['phase_b']['count']}")
    print(f"   Costo: ${data['phase_b']['total_cost']:.6f} USD")
    print(f"   Karma: {data['phase_b']['total_karma']}")
    print(f"   Avg: {data['phase_b']['avg_karma_per_comment']:.2f} karma/comment")
    
    print(f"\n📈 ROI Ratio (A/B): {data['roi_ratio']:.2f}x")
    
    if data['top_posts']:
        print(f"\n🏆 Top Posts:")
        for i, post in enumerate(data['top_posts'][:3], 1):
            print(f"   {i}. {post.get('moltbook_id', 'N/A')[:10]}... - {post.get('karma_score', 0)} karma")
    
    if data['top_comments']:
        print(f"\n🏆 Top Comments:")
        for i, comment in enumerate(data['top_comments'][:3], 1):
            print(f"   {i}. {comment.get('moltbook_id', 'N/A')[:10]}... - {comment.get('karma_score', 0)} karma")
    
    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    print_dashboard(24)
