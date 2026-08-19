# -*- coding: utf-8 -*-
"""Tests del cooldown de topics fallidos en Phase A (anti-bucle, v5.11)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from phases import phase_a_content as pa


class TestTopicCooldown:
    def test_mark_and_in_cooldown(self, tmp_path, monkeypatch):
        cd = tmp_path / "cooldown.json"
        monkeypatch.setattr(pa, "_TOPIC_COOLDOWN_PATH", cd)
        pa._mark_topic_cooldown("resilience and circuit breakers in LLM agents", "validation_failed:too_short")
        assert pa._topic_in_cooldown("resilience and circuit breakers in LLM agents") is True

    def test_expires_after_ttl(self, tmp_path, monkeypatch):
        cd = tmp_path / "cooldown.json"
        monkeypatch.setattr(pa, "_TOPIC_COOLDOWN_PATH", cd)
        # forzar TTL minimo
        monkeypatch.setattr(pa, "TOPIC_COOLDOWN_MINUTES", 0.001)
        pa._mark_topic_cooldown("topic x", "reason")
        # forzar que el cooldown ya expiro: reescribir el archivo con fecha pasada
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        cd.write_text(json.dumps({"topic x": past}), encoding="utf-8")
        assert pa._topic_in_cooldown("topic x") is False

    def test_different_topic_not_affected(self, tmp_path, monkeypatch):
        cd = tmp_path / "cooldown.json"
        monkeypatch.setattr(pa, "_TOPIC_COOLDOWN_PATH", cd)
        pa._mark_topic_cooldown("toxic topic", "reason")
        assert pa._topic_in_cooldown("healthy topic") is False

    def test_normalizes_case_and_spacing(self, tmp_path, monkeypatch):
        cd = tmp_path / "cooldown.json"
        monkeypatch.setattr(pa, "_TOPIC_COOLDOWN_PATH", cd)
        pa._mark_topic_cooldown("  Resilience AND Circuit Breakers  ", "reason")
        assert pa._topic_in_cooldown("resilience and circuit breakers") is True

    def test_no_topic_noop(self, tmp_path, monkeypatch):
        cd = tmp_path / "cooldown.json"
        monkeypatch.setattr(pa, "_TOPIC_COOLDOWN_PATH", cd)
        pa._mark_topic_cooldown("", "reason")
        assert pa._topic_in_cooldown("") is False
        assert not cd.exists() or json.loads(cd.read_text(encoding="utf-8")) == {}