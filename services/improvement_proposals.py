# -*- coding: utf-8 -*-
"""Generador de propuestas de mejora accionables (ejemplo para auto-mejora con aprobación)."""
from typing import List, Dict

def generate_improvement_proposals(metrics, posts, errors):
    """Genera propuestas basadas en datos reales (ejemplo)."""
    proposals = []
    # Ejemplo 1: storytelling
    storytelling_posts = [p for p in posts if 'story' in p.get('topic', '').lower()]
    if storytelling_posts and len(storytelling_posts) >= 3:
        avg_karma_story = sum(p.get('karma', 0) for p in storytelling_posts) / len(storytelling_posts)
        avg_karma_other = sum(p.get('karma', 0) for p in posts if p not in storytelling_posts) / max(1, len(posts) - len(storytelling_posts))
        if avg_karma_story > avg_karma_other * 1.5:
            proposals.append({
                "type": "prompt_adjustment",
                "title": "Aumentar storytelling en posts",
                "description": f"Posts con storytelling tienen {avg_karma_story:.0f} karma vs {avg_karma_other:.0f} de otros",
                "change": {"file": "phases/prompt_templates.py", "line": 45, "old": "Escribe un post analítico", "new": "Escribe un post con narrativa: setup → conflicto → insight"},
                "impact": "Esperado: +50% engagement",
                "confidence": 0.8
            })
    # Ejemplo 2: HF errores >50%
    hf_errors = [e for e in errors if 'huggingface' in e.get('provider', '').lower()]
    if errors and len(hf_errors) > len(errors) * 0.5:
        proposals.append({
            "type": "config_change",
            "title": "Reducir prioridad de HuggingFace",
            "description": f"{len(hf_errors)}/{len(errors)} errores son de HuggingFace",
            "change": {"file": "services/model_cascade.py", "line": 616, "old": "huggingface_flash: priority = -4", "new": "huggingface_flash: priority = -2"},
            "impact": "Esperado: -30% errores de conexión",
            "confidence": 0.9
        })
    return proposals

if __name__ == "__main__":
    # Test dummy
    posts = [{"topic": "story test", "karma": 100}, {"topic": "other", "karma": 10}]
    errors = [{"provider": "huggingface_flash"}, {"provider": "huggingface_flash"}, {"provider": "cloudflare"}]
    print(generate_improvement_proposals(posts, posts, errors))
