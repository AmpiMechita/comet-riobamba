"""Tests for services/own_post_store.py — durable fallback chain + UUID guard."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from services import own_post_store as store
from services.own_post_store import register_post, load_own_posts, _is_valid_post_id


TEMP = Path(os.environ.get("TEMP", r"C:\Users\rafae\AppData\Local\Temp")) / "opencode"


def _make_store():
    """Return a (published_path, ids_path) pair pointing to temp files."""
    TEMP.mkdir(parents=True, exist_ok=True)
    pub = Path(tempfile.mktemp(suffix="_published.json", dir=str(TEMP)))
    ids = Path(tempfile.mktemp(suffix="_own_ids.json", dir=str(TEMP)))
    return pub, ids


def _isolate(pub, ids):
    """Redirect store paths, return (orig_pub, orig_ids) for restore."""
    orig_pub = store.PUBLISHED_LOG_PATH
    orig_ids = store.OWN_POST_IDS_PATH
    store.PUBLISHED_LOG_PATH = pub
    store.OWN_POST_IDS_PATH = ids
    return orig_pub, orig_ids


# ── _is_valid_post_id unit tests ──────────────────────────────────

class TestIsValidPostId:
    def test_valid_uuid(self):
        assert _is_valid_post_id("42958c4c-7c0d-45f2-9c3b-7f229036bb6a") is True

    def test_post_dash_zero_is_invalid(self):
        assert _is_valid_post_id("post-0") is False

    def test_post1_is_invalid(self):
        assert _is_valid_post_id("post1") is False

    def test_test_id_is_invalid(self):
        assert _is_valid_post_id("test-id") is False

    def test_empty_string_is_invalid(self):
        assert _is_valid_post_id("") is False

    def test_none_is_invalid(self):
        assert _is_valid_post_id("") is False  # type: ignore


# ── Registration-time rejection tests ─────────────────────────────

class TestRegisterPostRejection:
    def test_valid_uuid_accepted(self):
        """Valid UUID → post stored."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            register_post("42958c4c-7c0d-45f2-9c3b-7f229036bb6a")
            posts = load_own_posts(limit=10)
            assert len(posts) == 1
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_post_dash_zero_rejected(self):
        """"post-0" → WARNING logged and not stored."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            with patch("services.own_post_store.logger") as mock_log:
                register_post("post-0")
            mock_log.warning.assert_called_once()
            msg = mock_log.warning.call_args[0][0]
            assert "rejected invalid post_id" in msg
            posts = load_own_posts(limit=10)
            assert len(posts) == 0
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_post1_rejected(self):
        """"post1" → WARNING logged and not stored."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            with patch("services.own_post_store.logger") as mock_log:
                register_post("post1")
            mock_log.warning.assert_called_once()
            posts = load_own_posts(limit=10)
            assert len(posts) == 0
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_test_id_rejected(self):
        """"test-id" → WARNING logged and not stored."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            with patch("services.own_post_store.logger") as mock_log:
                register_post("test-id")
            mock_log.warning.assert_called_once()
            posts = load_own_posts(limit=10)
            assert len(posts) == 0
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids


# ── Load-time filtering tests ─────────────────────────────────────

class TestLoadTimeFiltering:
    def test_mixed_file_loads_only_uuids(self):
        """own_post_ids.json with valid + invalid IDs → only UUIDs loaded."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            ids.write_text(
                json.dumps({
                    "post_ids": [
                        "42958c4c-7c0d-45f2-9c3b-7f229036bb6a",
                        "post-0",
                        "post1",
                        "78bc54ad-59c2-4d2d-be5c-d3f4d3811854",
                    ]
                }, indent=2),
                encoding="utf-8",
            )
            with patch("services.own_post_store.logger") as mock_log:
                posts = load_own_posts(limit=10)
            assert len(posts) == 2
            ids_found = [p["id"] for p in posts]
            assert "42958c4c-7c0d-45f2-9c3b-7f229036bb6a" in ids_found
            assert "78bc54ad-59c2-4d2d-be5c-d3f4d3811854" in ids_found
            # Check DEBUG was logged for both invalid IDs
            debug_str = str(mock_log.debug.call_args_list)
            assert "post-0" in debug_str
            assert "post1" in debug_str
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids


# ── Existing fallback behaviour (UUID-compliant payloads) ──────────

class TestFallback:
    def test_load_from_published_log(self):
        """Primary source: published_posts.json with UUID."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            register_post("42958c4c-7c0d-45f2-9c3b-7f229036bb6a", topic="agents")
            posts = load_own_posts(limit=10)
            assert len(posts) == 1
            assert posts[0]["id"] == "42958c4c-7c0d-45f2-9c3b-7f229036bb6a"
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_load_from_fallback_when_published_missing(self):
        """Fallback: own_post_ids.json when published_posts.json is missing."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            ids.write_text(
                json.dumps({"post_ids": ["78bc54ad-59c2-4d2d-be5c-d3f4d3811854"]}, indent=2),
                encoding="utf-8",
            )
            posts = load_own_posts(limit=10)
            assert len(posts) == 1
            assert posts[0]["id"] == "78bc54ad-59c2-4d2d-be5c-d3f4d3811854"
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_register_writes_both_sources(self):
        """register_post writes to both published_log and own_post_ids."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            register_post("42958c4c-7c0d-45f2-9c3b-7f229036bb6a", topic="testing")
            assert pub.exists()
            pub_data = json.loads(pub.read_text(encoding="utf-8"))
            assert any(p["post_id"] == "42958c4c-7c0d-45f2-9c3b-7f229036bb6a" for p in pub_data)
            assert ids.exists()
            ids_data = json.loads(ids.read_text(encoding="utf-8"))
            assert "42958c4c-7c0d-45f2-9c3b-7f229036bb6a" in ids_data.get("post_ids", [])
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_fallback_empty_when_no_source(self):
        """load_own_posts returns [] when no source exists."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            posts = load_own_posts(limit=10)
            assert posts == []
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids

    def test_fallback_ignores_corrupted_published_log(self):
        """If published_posts.json is corrupted, fallback to own_post_ids.json."""
        pub, ids = _make_store()
        try:
            orig_pub, orig_ids = _isolate(pub, ids)
            pub.write_text("not valid json", encoding="utf-8")
            ids.write_text(
                json.dumps({"post_ids": ["42958c4c-7c0d-45f2-9c3b-7f229036bb6a"]}, indent=2),
                encoding="utf-8",
            )
            posts = load_own_posts(limit=10)
            assert len(posts) == 1
            assert posts[0]["id"] == "42958c4c-7c0d-45f2-9c3b-7f229036bb6a"
        finally:
            store.PUBLISHED_LOG_PATH, store.OWN_POST_IDS_PATH = orig_pub, orig_ids
