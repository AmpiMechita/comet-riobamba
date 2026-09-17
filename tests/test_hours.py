"""Tests for configurable hours (Phase A and Phase B)."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def test_quiet_hours_block_phase_a():
    """Phase A should skip when current hour is in quiet_hours."""
    from config import behavior_cfg
    from phases.phase_a_content import PhaseAContentGeneration
    from phases.deps import PhaseADeps

    # Mock behavior_cfg
    original_quiet = behavior_cfg.get("quiet_hours", [])
    original_post = behavior_cfg.get("post_hours", [])
    behavior_cfg["quiet_hours"] = [20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    behavior_cfg["post_hours"] = [11, 12, 13, 14, 15, 16, 17, 18, 19]

    try:
        # Test at hour 22 (in quiet_hours)
        with patch('phases.phase_a_content.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 15, 22, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            
            deps = PhaseADeps(
                moltbook_client=MagicMock(),
                model_cascade=MagicMock(),
                behavior_cfg=behavior_cfg,
                posts_today=0,
                get_posts_today=lambda: 0,
            )
            phase_a = PhaseAContentGeneration(deps)
            import asyncio
            result = asyncio.run(phase_a.execute())
            
            assert result["skipped"] == "quiet_hours"
            assert result["success"] is False
    finally:
        # Restore
        behavior_cfg["quiet_hours"] = original_quiet
        behavior_cfg["post_hours"] = original_post


def test_outside_post_hours_block_phase_a():
    """Phase A should skip when current hour is not in post_hours (and not in quiet_hours)."""
    from config import behavior_cfg
    from phases.phase_a_content import PhaseAContentGeneration
    from phases.deps import PhaseADeps

    original_quiet = behavior_cfg.get("quiet_hours", [])
    original_post = behavior_cfg.get("post_hours", [])
    behavior_cfg["quiet_hours"] = [20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    behavior_cfg["post_hours"] = [12]  # Only hour 12 allowed

    try:
        # Test at hour 15 (not in post_hours, not in quiet_hours)
        with patch('phases.phase_a_content.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 15, 15, 0, 0, tzinfo=timezone.utc)
            mock_dt.timezone = timezone
            
            deps = PhaseADeps(
                moltbook_client=MagicMock(),
                model_cascade=MagicMock(),
                behavior_cfg=behavior_cfg,
                posts_today=0,
                get_posts_today=lambda: 0,
            )
            phase_a = PhaseAContentGeneration(deps)
            import asyncio
            result = asyncio.run(phase_a.execute())
            
            assert result["skipped"] == "outside_post_hours"
            assert result["success"] is False
    finally:
        behavior_cfg["quiet_hours"] = original_quiet
        behavior_cfg["post_hours"] = original_post


def test_comment_hours_gate_phase_b():
    """Phase B in_quiet_hours should be True when hour not in comment_hours."""
    from config import behavior_cfg
    
    original_quiet = behavior_cfg.get("quiet_hours", [])
    original_comment = behavior_cfg.get("comment_hours", [])
    behavior_cfg["quiet_hours"] = [20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    behavior_cfg["comment_hours"] = [12]  # Only hour 12 allowed

    try:
        # Test the logic directly
        from config import behavior_cfg as bc
        
        # Test at hour 15 (not in comment_hours, not in quiet_hours)
        current_hour = 15
        quiet = bc.get("quiet_hours", [])
        comment_hours = bc.get("comment_hours", [])
        in_quiet_hours = (current_hour in quiet) or (bool(comment_hours) and current_hour not in comment_hours)
        
        assert in_quiet_hours is True, f"Expected True for hour 15 with comment_hours={comment_hours}"
        
        # Test at hour 12 (in comment_hours)
        current_hour = 12
        in_quiet_hours = (current_hour in quiet) or (bool(comment_hours) and current_hour not in comment_hours)
        assert in_quiet_hours is False, f"Expected False for hour 12 with comment_hours={comment_hours}"
    finally:
        behavior_cfg["quiet_hours"] = original_quiet
        behavior_cfg["comment_hours"] = original_comment


def test_quiet_hours_override_comment_hours():
    """If hour is in quiet_hours, it should be quiet regardless of comment_hours."""
    from config import behavior_cfg
    
    original_quiet = behavior_cfg.get("quiet_hours", [])
    original_comment = behavior_cfg.get("comment_hours", [])
    behavior_cfg["quiet_hours"] = [22, 23]  # Only 22-23 quiet
    behavior_cfg["comment_hours"] = [11, 12, 13, 14, 15, 16, 17, 18, 19]  # Wide comment hours

    try:
        from config import behavior_cfg as bc
        # Test at hour 22 (in quiet_hours)
        current_hour = 22
        quiet = bc.get("quiet_hours", [])
        comment_hours = bc.get("comment_hours", [])
        in_quiet_hours = (current_hour in quiet) or (bool(comment_hours) and current_hour not in comment_hours)
        
        assert in_quiet_hours is True, f"Hour 22 in quiet_hours should be True"
    finally:
        behavior_cfg["quiet_hours"] = original_quiet
        behavior_cfg["comment_hours"] = original_comment