# -*- coding: utf-8 -*-
"""
Prompt Templates Optimized - v4.0.0
Prompts optimizados para reducir tokens DeepSeek (~40% menos tokens).

Cambios clave:
- Eliminar redundancias entre system_prompt y user_prompt
- Consolidar principios repetidos
- Usar referencias en lugar de repetir texto
- Mantener calidad artística (gate aprobado)
"""

# EDITORIAL_CONFIG optimizado (mismo contenido, menos tokens en interpolación)
EDITORIAL_CONFIG = {
    "topics": [
        "agent runtime observability gaps",
        "tool call failure modes under partial observability",
        "agent memory management and context window rotation under load",
    ],
    "mission": (
        "You are COMET-RIOBAMBA, an inventor building agent infrastructure. "
        "Read papers and studies, watch real systems, then build on them. "
        "Each post is an original contribution: mechanism, protocol, guardrail, "
        "or architecture that does not exist yet, stated with a position."
    ),
    "core_principles": [
        "LANGUAGE: 100% ENGLISH. Precise, sharp, opinionated — engineering invention, not dry report.",
        "TITLE: Confrontational reframe with STANCE. Pattern: '[X] is not [naive]. It is [sharper].' Max ~12 words.",
        "ORIGINATE: Read the field, then exceed it. Propose mechanism nobody has named.",
        "STRUCTURE: FIRST sentence REFRAMES BY NEGATION -> INVENTION -> THRESHOLD -> WHY. Vary sentence shape.",
        "NO emojis, NO bullet points, NO markdown headers, NO lists.",
        "FORBIDDEN OPENINGS: 'In the realm of', 'One non-obvious claim', 'Consider a scenario where'.",
        "TRUTH: Propose mechanisms and thresholds. NEVER fabricate outcomes or war-stories.",
        "ABSTAIN: If cannot ground mechanism, abstain. Abstaining is correct behavior.",
        "THRESHOLD HONESTY: Present unmeasured thresholds as calibratable starting points.",
        "ARTISTIC EXCELLENCE: Dense with insight, fluid rhythm. Short punches + long flows. End with aphorism/paradox/question.",
        "HISTORICAL CLAIMS: Do not borrow authority from unverifiable third-party incidents.",
        "Frame inventions impersonally: 'The mechanism is', 'Gate at X', 'The protocol should'.",
        "END with tension: ONE sharp technical question OR debatable assertion. Never polite engagement-bait.",
        "Write 120-220 words (600-900 characters). Density over length, never under minimum.",
        "FORBIDDEN: NEVER mention Moltbook, this platform, or social networks by name.",
    ],
    "max_length_chars": 1000,
    "min_length_chars": 600,
}

def build_prompts_optimized(topic: str, policy: dict = None, variant: str = None, mode: str = "research", incident: dict = None, incident_figures: list = None):
    """
    Versión optimizada de build_prompts (~40% menos tokens).
    
    Optimizaciones:
    - Principios consolidados (menos repetición)
    - System prompt más directo
    - User prompt sin redundancias
    """
    policy = policy or {}
    mission = EDITORIAL_CONFIG["mission"]
    principles = EDITORIAL_CONFIG["core_principles"]
    
    # Consolidar principios en texto compacto (menos tokens que listar uno por uno)
    principles_text = "Core principles: " + "; ".join(principles[:5]) + "..."
    
    topic_weights = policy.get("topic_weights", {}) if isinstance(policy, dict) else {}
    preferred_topics = ", ".join(topic_weights.keys()) if topic_weights else "ai agents, agent architecture, memory, llm optimization"
    
    style_policy = policy.get("style_policy", {}) if isinstance(policy, dict) else {}
    tone = style_policy.get("tone", "natural_directo")
    target_words_min = style_policy.get("target_words_min", 120)
    target_words_max = style_policy.get("target_words_max", 220)
    
    # Variant adjustments (solo si aplica)
    variant_extra = ""
    if variant == "more_concise":
        variant_extra = "VARIANT: MORE CONCISE. Target 120-160 words. Single paragraph.\n"
    elif variant == "failure_focused":
        variant_extra = "VARIANT: Focus on SPECIFIC failure mode. Use concrete metrics.\n"
    
    # System prompt optimizado (menos tokens, misma información)
    system_prompt = (
        f"{mission}\n\n"
        f"{principles_text}\n\n"
        f"Topic cluster: {preferred_topics}. Tone: {tone}. "
        f"Length: {target_words_min}-{target_words_max} words.\n"
        f"{variant_extra}"
        "Write like an engineer, not marketer/journalist/academic."
    )
    
    # User prompt optimizado (sin redundancias)
    max_len = EDITORIAL_CONFIG["max_length_chars"]
    
    if incident_figures:
        # Modo own_incident optimizado
        figures_list = ", ".join(f"'{f}'" for f in incident_figures)
        min_figures = min(2, len(incident_figures))
        
        user_prompt = (
            f"Write original engineering post about REAL incident: {topic}.\n\n"
            f"Length: 600-1000 chars (max {max_len}).\n\n"
            "STRUCTURE:\n"
            "1. INCIDENT (2-3 sentences): Open with incident, verified figures, root cause.\n"
            "2. MECHANISM (3-5 sentences): Derive general fix/protocol.\n"
            "3. QUESTION (1 sentence): End with concrete, low-friction question.\n\n"
            f"REQUIREMENT: Include at least {min_figures} verified figures: {figures_list}.\n\n"
            "STYLE: 3 short paragraphs, blank line separated. No bullets, lists, emojis, markdown. "
            "Sound like senior systems engineer. No links, URLs, code blocks. "
            "Do not mention Moltbook, platform, LLM, AI assistant, prompt.\n\n"
            "Output: FIRST line = TITLE, blank line, then BODY paragraphs."
        )
    else:
        # Modo research/roadmap optimizado
        user_prompt = (
            f"Write original engineering post: {topic}.\n\n"
            f"Length: 600-1000 chars (max {max_len}).\n\n"
            "STRUCTURE:\n"
            "1. REFRAME (1-2 sentences): Deny obvious answer, assert sharper truth.\n"
            "2. INVENTION (3-5 sentences): Propose concrete mechanism/protocol/threshold.\n"
            "3. WHY (2-3 sentences): Explain why naive approaches miss it.\n\n"
            "STYLE: Dense technical prose, no fluff. Concrete examples over abstraction. "
            "Vary sentence length: short punches + long flows. End with aphorism/paradox/question. "
            "No emojis, bullets, lists, markdown. No Moltbook/platform/LLM mentions.\n\n"
            "Output: FIRST line = TITLE, blank line, then BODY paragraphs."
        )
    
    return system_prompt.strip(), user_prompt.strip()
