import pytest

from personality.modes import (
    select_mode,
    get_mode_prompt,
    COMMUNICATION_MODES,
)


# ---------------------------------------------------------------------------
# Test 1: Default is Architect
# ---------------------------------------------------------------------------

def test_default_is_architect():
    assert select_mode(None, {}) == "architect"


# ---------------------------------------------------------------------------
# Test 2: Pattern break intervention → Provocateur
# ---------------------------------------------------------------------------

def test_pattern_break_intervention():
    diagnosis = {"intervention_required": True, "interventions": ["pattern_break"]}
    assert select_mode(diagnosis, {}) == "provocateur"


# ---------------------------------------------------------------------------
# Test 3: Topic rotation intervention → Historian
# ---------------------------------------------------------------------------

def test_topic_rotation_intervention():
    diagnosis = {"intervention_required": True, "interventions": ["topic_rotation"]}
    assert select_mode(diagnosis, {}) == "historian"


# ---------------------------------------------------------------------------
# Test 4: Long thread → Synthesizer
# ---------------------------------------------------------------------------

def test_long_thread_synthesizer():
    assert select_mode(None, {"thread_reply_count": 4}) == "synthesizer"


# ---------------------------------------------------------------------------
# Test 5: Intervention priority over long thread
# ---------------------------------------------------------------------------

def test_intervention_priority_over_thread():
    diagnosis = {"intervention_required": True, "interventions": ["pattern_break"]}
    assert select_mode(diagnosis, {"thread_reply_count": 5}) == "provocateur"


# ---------------------------------------------------------------------------
# Test 6: Evaluation cluster → Empiricist
# ---------------------------------------------------------------------------

def test_evaluation_cluster_empiricist():
    assert select_mode(None, {"topic_cluster": "evaluation"}) == "empiricist"


# ---------------------------------------------------------------------------
# Test 7: get_mode_prompt formatting
# ---------------------------------------------------------------------------

def test_get_mode_prompt_provocateur():
    prompt = get_mode_prompt("provocateur")
    assert "NEVER start with" in prompt
    assert "FORBIDDEN" in prompt
    assert "PROVOCATEUR" in prompt


# ---------------------------------------------------------------------------
# Test 8: Historian cluster without diagnosis
# ---------------------------------------------------------------------------

def test_historian_cluster():
    assert select_mode(None, {"topic_cluster": "historical"}) == "historian"
    assert select_mode(None, {"topic_cluster": "fringe"}) == "historian"


# ---------------------------------------------------------------------------
# Test 9: All modes have required keys
# ---------------------------------------------------------------------------

def test_all_modes_valid():
    required_keys = {"tone", "structural_rules", "forbidden"}
    for mode_name, config in COMMUNICATION_MODES.items():
        assert required_keys.issubset(config.keys()), f"Mode {mode_name} missing keys"
        assert isinstance(config["structural_rules"], list) and len(config["structural_rules"]) >= 4
        assert isinstance(config["forbidden"], list)
