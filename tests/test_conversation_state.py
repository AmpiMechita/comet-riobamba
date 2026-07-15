"""Tests for UUID guards in services/conversation_state.py."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from services import conversation_state as cs
from services.own_post_store import is_valid_post_id

TEMP = Path(os.environ.get("TEMP", r"C:\Users\rafae\AppData\Local\Temp")) / "opencode"


def _make_path():
    TEMP.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mktemp(suffix="_conv.json", dir=str(TEMP)))


class TestConversationStateUuidGuard:
    def test_non_uuid_rejected_at_write(self):
        """Non-UUID post_id in get_or_create_thread is rejected with WARNING."""
        path = _make_path()
        try:
            orig = cs.CONVERSATIONS_PATH
            cs.CONVERSATIONS_PATH = path
            with patch("services.conversation_state.logger") as mock_log:
                result = cs.get_or_create_thread("post1")
            assert result == {"turns_in_thread": 0, "open_questions": False, "closed": False}
            mock_log.warning.assert_called_once()
            msg = mock_log.warning.call_args[0][0]
            assert "rejected non-UUID" in msg
            assert "post1" in str(mock_log.warning.call_args)
            # Verify file was NOT written
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                assert "post1" not in data
            cs.CONVERSATIONS_PATH = orig
        finally:
            if path.exists():
                path.unlink()

    def test_mixed_file_load_keeps_only_uuids(self):
        """Loading a file with mixed UUIDs and non-UUIDs keeps only UUIDs."""
        path = _make_path()
        try:
            orig = cs.CONVERSATIONS_PATH
            cs.CONVERSATIONS_PATH = path
            path.write_text(json.dumps({
                "42958c4c-7c0d-45f2-9c3b-7f229036bb6a": {"turns_in_thread": 0, "open_questions": False, "closed": False},
                "post1": {"turns_in_thread": 5, "open_questions": True, "closed": False},
                "78bc54ad-59c2-4d2d-be5c-d3f4d3811854": {"turns_in_thread": 2, "open_questions": False, "closed": False},
                "test-id": {"turns_in_thread": 1, "open_questions": False, "closed": False},
            }), encoding="utf-8")
            result = cs._load_conversations()
            assert "42958c4c-7c0d-45f2-9c3b-7f229036bb6a" in result
            assert "78bc54ad-59c2-4d2d-be5c-d3f4d3811854" in result
            assert "post1" not in result
            assert "test-id" not in result
            assert len(result) == 2
            cs.CONVERSATIONS_PATH = orig
        finally:
            if path.exists():
                path.unlink()
