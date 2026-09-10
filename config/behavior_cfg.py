# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v4.3.0 - Behavior config

Controla:
- Intervalo base de ciclos (cycle_interval_seconds)
- Límites diarios de publicación
- Activación de Fase B (respuestas) y Fase C (analytics)
- Parámetros de tono y filtros para Fase B
- Configuración del modelo local Ollama
"""

behavior_cfg = {
    # Modo whisper: no publica posts ni replies reales, sólo genera y loguea
    "whisper_mode": False,

    # ============================
    # Phase A - Post generation
    # ============================
    "phase_a_enabled": True,

    # Horas permitidas para publicar posts (UTC-5, hora local Ecuador)
    "post_publish_hours": [12, 13, 18, 19, 20, 21],

    # Intervalo base de ciclo en segundos
    "cycle_interval_seconds": 300,

    # Límite diario y objetivo de posts
    "max_posts_per_day": None,
    "value_review_interval_days": 7,
    "posts_per_day": 1,

    # ============================
    # Modelo local / Ollama
    # ============================
    "ollama_model": "qwen2.5:3b",
    "ollama_base_url": "http://localhost:11434/v1/chat/completions",

    # ============================
    # Phase B - Community replies
    # ============================
    "phase_b_enabled": True,
    "comment_valle_hours": [18, 19, 20, 21, 22, 23, 0, 1],
    "phase_b_feed_replies": False,
    "phase_b_max_replies": None,
    "max_comments_per_day": 150,

    # Tono de las respuestas
    "phase_b_reply_tone": "cordial-tecnico",
    "phase_b_avoid_topics": ["política", "religión"],

    # ============================
    # Phase C - Analytics
    # ============================
    "phase_c_enabled": True,
    "max_phase_c_replies_per_day": 50,
}
