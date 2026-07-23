# -*- coding: utf-8 -*-
"""Tests for services/energy_intel_telegram.py — puente a research_agenda."""

from unittest.mock import MagicMock, patch

import services.energy_intel_telegram as eit


def test_bridge_adds_topic_on_crossover_keyword():
    """Título/resumen con palabra de cruce → agenda.add_topic() con topic enmarcado."""
    agenda = MagicMock()
    with patch("services.research_agenda.load_agenda", return_value=agenda), \
         patch("services.research_agenda.save_agenda") as mock_save:
        eit._maybe_bridge_to_agenda(
            "Drones inspect offshore wind turbines",
            "predictive maintenance cuts downtime by 30%",
            "wind", "frontier_claim",
        )

    agenda.add_topic.assert_called_once()
    topic = agenda.add_topic.call_args[0][0]
    assert "production reliability of autonomous agents" in topic
    assert "wind" in topic
    assert agenda.add_topic.call_args.kwargs["source"] == "energy_intel_bridge"
    assert agenda.add_topic.call_args.kwargs["tags"] == ["energy_intel", "wind"]
    mock_save.assert_called_once_with(agenda)


def test_bridge_ignores_entries_without_crossover_signal():
    """Sin palabra de cruce, la agenda no se toca."""
    with patch("services.research_agenda.load_agenda") as mock_load, \
         patch("services.research_agenda.save_agenda") as mock_save:
        eit._maybe_bridge_to_agenda(
            "New solar panel coating boosts efficiency",
            "perovskite lab results look promising",
            "solar", "tech_radar_scan",
        )

    mock_load.assert_not_called()
    mock_save.assert_not_called()


def test_bridge_swallows_exceptions(caplog):
    """Si load_agenda falla, no propaga — solo warning."""
    with patch("services.research_agenda.load_agenda", side_effect=RuntimeError("boom")), \
         patch("services.research_agenda.save_agenda") as mock_save, \
         caplog.at_level("WARNING", logger="services.energy_intel_telegram"):
        eit._maybe_bridge_to_agenda(
            "Agent-based grid management pilot", "", "grid", "funding_scan"
        )

    mock_save.assert_not_called()
    assert any("bridge to agenda failed" in r.message for r in caplog.records)
