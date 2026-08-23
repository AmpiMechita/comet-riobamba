# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v5.0 - config/__init__.py
==========================================
Re-exporta la API pública del paquete config desde config.config.
"""

from config.agent_policy import POLICY as POLICY
from config.config import (
    BASE_DIR,
    behavior_cfg,
    content_cfg,
    moltbook_cfg,
    logging_cfg,
    validate_config,
    bootstrap_directories,
    get_banner,
    AgentVersion,
    AGENT_NAME,
    LOGS_DIR,
    DATA_DIR,
    OUTBOX_DB_PATH,
    TOPIC_MEMORY_DB_PATH,
    CACHE_DB_PATH,
    POST_HISTORY_DB_PATH,
)

__all__ = [
    "BASE_DIR",
    "POLICY",
    "behavior_cfg",
    "content_cfg",
    "moltbook_cfg",
    "logging_cfg",
    "validate_config",
    "bootstrap_directories",
    "get_banner",
    "AgentVersion",
    "AGENT_NAME",
    "LOGS_DIR",
    "DATA_DIR",
    "OUTBOX_DB_PATH",
    "TOPIC_MEMORY_DB_PATH",
    "CACHE_DB_PATH",
    "POST_HISTORY_DB_PATH",
]