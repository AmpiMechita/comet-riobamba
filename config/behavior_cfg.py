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

    # Intervalo base de ciclo en segundos (8 horas)
    # El core usa: base_interval = behavior_cfg.get("cycle_interval_seconds", 14400)
    "cycle_interval_seconds": 28800,

    # Límite diario y objetivo de posts
    # Phase A calcula remaining_today con estos valores
    "max_posts_per_day": 5,   # techo duro por día
    "value_review_interval_days": 7,  # cada 7 días genera plan de mejora
    "posts_per_day": 1,       # objetivo diario (en tu caso 1 post por día)

    # ============================
    # Modelo local / Ollama
    # ============================
    "ollama_model": "qwen2.5:3b",
    "ollama_base_url": "http://localhost:11434/v1/chat/completions",

    # ============================
    # Phase B - Community replies
    # ============================
    # El core sólo ejecuta Phase B si:
    # - behavior_cfg["phase_b_enabled"] es True
    # - whisper_mode es False
    "phase_b_enabled": True,

    # Máximo de replies por ciclo (Phase B usa behavior_cfg.get("phase_b_max_replies", ...))
    "phase_b_max_replies": 1,

    # Tono de las respuestas (Phase B lo usa para construir el prompt)
    "phase_b_reply_tone": "cordial-tecnico",

    # Tópicos a evitar en respuestas (Phase B filtra comentarios que los contengan)
    "phase_b_avoid_topics": [
        "política",
        "religión",
    ],

    # ============================
    # Phase C - Analytics
    # ============================
    # Activa/desactiva Fase C (el core revisa phase_c_enabled antes de _run_phase_c)
    "phase_c_enabled": True,
}