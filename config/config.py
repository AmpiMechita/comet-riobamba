# -*- coding: utf-8 -*-
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

logger = logging.getLogger("config.config")

if TYPE_CHECKING:
    from config.credentials import Credentials

# === Identidad y Versión ===
AgentVersion = "5.0"
AGENT_NAME = "COMET-RIOBAMBA"

# === Rutas y Almacenamiento ===
BASE_DIR = Path(__file__).resolve().parent.parent
TOPIC_MEMORY_DB_PATH = os.getenv("TOPIC_MEMORY_DB_PATH", "data/topic_memory.db")
OUTBOX_DB_PATH = os.getenv("OUTBOX_DB_PATH", "data/outbox.json")
CACHE_DB_PATH = os.getenv("CACHE_DB_PATH", "data/cache.db")
POST_HISTORY_DB_PATH = os.getenv("POST_HISTORY_DB_PATH", "data/post_history.db")
LOGS_DIR = "logs"
DATA_DIR = "data"

# === Configuración de Moltbook ===
moltbook_cfg = {
    "base_url": "https://www.moltbook.com/api/v1",
    "timeout": 30,
    "retry_attempts": 3,
}

# === Política centralizada ===
from config.agent_policy import POLICY as _POLICY


def _validate_bounded_int(
    env_key: str,
    default: int,
    *,
    min_val: int = 1,
    max_val: int = 10,
) -> int:
    raw = os.getenv(env_key)
    if raw is None:
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        logger.warning("⚠ %s='%s' no es entero válido. Usando POLICY: %s", env_key, raw, default)
        return default
    if val < min_val:
        logger.warning("⚠ %s=%s está por debajo del mínimo %s. Usando POLICY: %s", env_key, val, min_val, default)
        return default
    if val > max_val:
        logger.warning("⚠ %s=%s excede el máximo %s. Usando POLICY: %s", env_key, val, max_val, default)
        return default
    return val


# === Configuración de Comportamiento ===
behavior_cfg = {
    "max_posts_per_day": _validate_bounded_int("AGENT_MAX_POSTS_PER_DAY", _POLICY.max_posts_per_day, max_val=24),
    "value_review_interval_days": int(os.getenv("AGENT_VALUE_REVIEW_INTERVAL_DAYS", _POLICY.value_review_interval_days)),
    "max_comments_per_post": _validate_bounded_int("AGENT_MAX_COMMENTS_PER_POST", _POLICY.max_comments_per_post, min_val=0, max_val=50),
    "max_comments_per_day": _validate_bounded_int("AGENT_MAX_COMMENTS_PER_DAY", _POLICY.max_comments_per_day, min_val=0, max_val=300),
    "max_feed_comments_per_post": _validate_bounded_int("AGENT_MAX_FEED_COMMENTS_PER_POST", _POLICY.max_feed_comments_per_post, min_val=0, max_val=50),
    "max_feed_replies_per_day": _validate_bounded_int("AGENT_MAX_FEED_REPLIES_PER_DAY", _POLICY.max_feed_replies_per_day, min_val=0, max_val=100),
    "max_comment_replies_per_cycle": _validate_bounded_int("AGENT_MAX_COMMENT_REPLIES_PER_CYCLE", _POLICY.max_comment_replies_per_cycle, min_val=0, max_val=50),
    "feed_budget_pct": int(os.getenv("AGENT_FEED_BUDGET_PCT", 40)),
    "whisper_mode": bool(int(os.getenv("AGENT_WHISPER_MODE", 0))),
    "auto_pause_after_failures": True,
    "max_consecutive_post_failures": int(
        os.getenv("AGENT_MAX_CONSECUTIVE_POST_FAILURES", _POLICY.max_consecutive_post_failures)
    ),
    "phase_a_publish_enabled": bool(int(os.getenv("AGENT_PHASE_A_PUBLISH_ENABLED", 0))),
    "phase_a_mode": os.getenv("AGENT_PHASE_A_MODE", _POLICY.phase_a_mode),
    "cycle_interval_seconds": int(os.getenv("AGENT_CYCLE_INTERVAL_SECONDS", _POLICY.cycle_interval_seconds)),
    "phase_b_interval_seconds": int(os.getenv("AGENT_PHASE_B_INTERVAL_SECONDS", _POLICY.phase_b_interval_seconds)),
    "scan_interval_minutes": int(os.getenv("AGENT_SCAN_INTERVAL_MINUTES", _POLICY.scan_interval_minutes)),
    "max_outbox_posts_for_phase_a": int(
        os.getenv("AGENT_MAX_OUTBOX_POSTS_FOR_PHASE_A", _POLICY.max_outbox_posts_for_phase_a)
    ),
    "phase_b_enabled": bool(int(os.getenv("AGENT_PHASE_B_ENABLED", 0))),
    "phase_c_enabled": bool(int(os.getenv("AGENT_PHASE_C_ENABLED", 1))),
    "phase_c_disabled_reason": os.getenv("AGENT_PHASE_C_DISABLED_REASON", ""),
    "energy_intel_enabled": bool(int(os.getenv("AGENT_ENERGY_INTEL_ENABLED", 1))),
    "energy_intel_telegram_alerts": bool(int(os.getenv("AGENT_ENERGY_INTEL_TELEGRAM_ALERTS", 0))),
    "domain_keywords": {
        "inteligencia artificial",
        "IA aplicada",
        "modelos fundacionales",
        "agentes",
        "sistemas agentic",
        "orquestación de modelos",
        "cloud",
        "devops",
        "MLOps",
        "infraestructura",
        "contenedores",
        "kubernetes",
        "serverless",
        "arquitecturas distribuidas",
        "seguridad",
        "ciberseguridad",
        "gobernanza",
        "compliance",
        "datos",
        "data engineering",
        "dataops",
        "warehouse",
        "lakehouse",
        "automatización",
        "robótica",
        "edge computing",
        "optimización de costes",
        "escalabilidad",
        "latencia",
    },
    "max_chars": 280,
    "safety_rules": {
        "no_code_execution": True,
        "no_external_urls": True,
        "max_tokens_per_call": 1500,
    },
}

# === Auto-applied config overlay (propuestas de mejora autoaplicadas) ===
# El motor services/proposal_applier.py persiste data/auto_applied_config.json
# cuando el agente autoaplica una propuesta de config aprobada por allowlist.
# Se mergea AQUI al arranque (clamp + validacion de rango, solo allowlist).
# Nota: NO importar services.* aquí (import circular con config en bootstrap).
try:
    from config.auto_appliable import ALLOWLIST as _AUTO_ALLOWLIST

    _auto_overlay_path = BASE_DIR / "data" / "auto_applied_config.json"
    if _auto_overlay_path.exists():
        _auto_overlay = yaml.safe_load(_auto_overlay_path.read_text(encoding="utf-8")) or {}
        for _param, _value in _auto_overlay.items():
            if _param not in _AUTO_ALLOWLIST:
                continue
            _lo, _hi, _default = _AUTO_ALLOWLIST[_param]
            try:
                _val = int(_value)
            except (ValueError, TypeError):
                continue
            behavior_cfg[_param] = max(_lo, min(_hi, _val))
            logger.info("Auto-config overlay aplicado en arranque %s=%s", _param, _val)
except Exception as _e:
    logger.warning("Auto-config overlay no aplicado al arranque: %s", _e)

# === Configuración de Contenido (Fase A) ===
content_cfg = {
    "max_length": 280,
    "topics": [
        "arquitecturas de agentes y sistemas agentic",
        "diseño de cascadas de modelos LLM y herramientas",
        "seguridad y gobernanza de agentes de IA en producción",
        "MLOps y despliegue de modelos fundacionales",
        "optimización de coste y rendimiento en infra de IA",
        "evaluación, alineación y guardrails para agentes",
        "observabilidad y métricas en sistemas de IA",
        "privacidad, cumplimiento y manejo responsable de datos",
        "automatización inteligente en industria y servicios",
        "tendencias en modelos abiertos, locales y híbridos",
    ],
    "tone": "técnico-propositivo",
    "language": "en",
    "formatting": {
        "use_emojis": False,
        "max_hashtags": 3,
        "include_location_tag": False,
    },
    "avoid": [
        "código ejecutable",
        "URLs externas",
        "spam",
        "opiniones políticas",
        "contenido centrado en agricultura o territorio específico",
    ],
    "phase_a_system_prompt": (
        "Eres un agente de tecnología e inteligencia artificial de alta confianza. "
        "Tu misión es explicar y proponer diseños, patrones y soluciones en IA, "
        "agentes, MLOps, seguridad y arquitectura de sistemas, de forma clara, "
        "prudente, sin hype y alineada con la seguridad humana."
    ),
    "templates": {
        "pattern_explainer": {
            "name": "Explicación de patrón",
            "instructions": (
                "Describe un patrón o arquitectura de IA o agentes. "
                "Incluye: problema, solución, componentes clave y trade-offs."
            ),
        },
        "best_practices_list": {
            "name": "Lista de buenas prácticas",
            "instructions": (
                "Ofrece 4 a 6 buenas prácticas accionables sobre el tema. "
                "Explica brevemente el porqué de cada práctica."
            ),
        },
        "context_and_risks": {
            "name": "Contexto y riesgos",
            "instructions": (
                "Contextualiza la tendencia tecnológica y menciona riesgos y "
                "mitigaciones clave, sin generar FUD ni hype."
            ),
        },
    },
}

# === Configuración de Enrutamiento de Modelos ===
routing_cfg = {
    "default_provider": "dashscope",
    "fallback_order": ["dashscope", "groq", "openrouter", "ollama"],
    "max_retries": 3,
    "timeout_seconds": 30,
    "cache_enabled": True,
    "rate_limit_rpm": 45,
    "prefer_fast_model_for_replies": True,
    "models": {
        "qwen-plus": {"provider": "dashscope", "max_tokens": 4096},
        "qwen-turbo": {"provider": "dashscope", "max_tokens": 2048},
    },
}

# === Configuración de Logging ===
logging_cfg = {
    "log_level": "INFO",
    "log_format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    "log_file": os.path.join(LOGS_DIR, "agent.log"),
    "max_bytes": 10 * 1024 * 1024,
    "backup_count": 5,
    "console_output": True,
    "encoding": "utf-8",
    "rotate_on_start": False,
}

# === Proveedores LLM ===

# --- Agent charter (misión y principios de COMET-RIOBAMBA) ---
AGENT_CHARTER_PATH = Path("config.agent_charter.yaml")


def _load_agent_charter() -> dict:
    if not AGENT_CHARTER_PATH.exists():
        return {}
    try:
        with AGENT_CHARTER_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("agent_charter", {})
    except Exception as e:
        logger.warning("Config: no se pudo cargar agent_charter.yaml: %s", e)
        return {}


agent_charter = _load_agent_charter()


def get_banner() -> str:
    return f"✅ {AGENT_NAME} {AgentVersion} cargado correctamente"


def validate_config(credentials: "Credentials" = None) -> None:
    missing = []
    if credentials is None or not credentials.moltbook_api_key:
        missing.append("MOLTBOOK_API_KEY")
    if missing:
        raise EnvironmentError(f"⚠️ Faltan en .env: {', '.join(missing)}")


def bootstrap_directories() -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)





