"""
LinkedIn text publisher.

Uses the LinkedIn Share API (v2) with OAuth 2.0 user tokens.

Setup (one-time, ~1 hour):
  1. Go to https://www.linkedin.com/developers/apps/new
  2. Create an app. Pick 'Marketing API' product (gives w_member_social).
  3. Add redirect URI: http://localhost:8080/callback
  4. Note CLIENT_ID and CLIENT_SECRET.
  5. Run:  python -m comet_repurposer.cli auth-linkedin
     -> Browser opens, you log in, we capture the authorization code,
        exchange for access_token + refresh_token, store them in .env.
  6. Tokens expire in 60 days. The publisher auto-refreshes using the
     refresh_token (good for 365 days). After 365 days you must re-auth.

Posting:
  POST https://api.linkedin.com/v2/ugcPosts
  with JSON body:
    {
      "author": "urn:li:person:<person_id>",
      "lifecycleState": "PUBLISHED",
      "specificContent": {
        "com.linkedin.ugc.ShareContent": {
          "shareCommentary": {"text": "<post text>"},
          "shareMediaCategory": "NONE"
        }
      },
      "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
"""

from __future__ import annotations

import json
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .base import (
    AuthError,
    BasePublisher,
    PublishError,
    PublishJob,
    PublishStatus,
    RateLimitError,
)


LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_ME_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_POST_URL = "https://api.linkedin.com/v2/ugcPosts"
LINKEDIN_REFRESH_URL = "https://www.linkedin.com/oauth/v2/accessToken"


class LinkedInPublisher(BasePublisher):
    """Post text to a LinkedIn personal profile."""

    platform = "linkedin"

    REQUIRED_KEYS = ["client_id", "client_secret", "access_token", "person_id"]

    def validate_credentials(self) -> None:
        missing = [k for k in ("client_id", "client_secret", "access_token", "person_id")
                   if not self.credentials.get(k)]
        if missing:
            raise AuthError(
                f"LinkedIn credentials missing: {missing}. "
                f"Run: python -m comet_repurposer.cli auth-linkedin"
            )

    def publish(self, job: PublishJob) -> PublishJob:
        """Publish one text post."""
        self.validate_credentials()

        text = job.payload_text.strip()
        if not text:
            job.status = PublishStatus.FAILED
            job.error = "Empty payload_text"
            return job

        if self.dry_run:
            job.status = PublishStatus.PUBLISHED  # virtual
            job.platform_post_id = f"dry-run:{self.platform}:{int(time.time())}"
            job.published_at = time.time()
            job.error = None
            return job

        token = self._ensure_fresh_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        body = {
            "author": f"urn:li:person:{self.credentials['person_id']}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text[:3000]},  # LinkedIn hard cap
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        try:
            resp = requests.post(LINKEDIN_POST_URL, headers=headers,
                                 json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            job.status = PublishStatus.FAILED
            job.error = f"network error: {exc}"
            return job

        if resp.status_code == 429:
            raise RateLimitError(f"LinkedIn 429: {resp.text[:200]}")
        if resp.status_code >= 400:
            job.status = PublishStatus.FAILED
            job.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            return job

        try:
            data = resp.json()
            job.platform_post_id = data.get("id") or data.get("activity")
        except ValueError:
            job.platform_post_id = f"unknown:{int(time.time())}"

        job.status = PublishStatus.PUBLISHED
        job.published_at = time.time()
        job.error = None
        return job

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    def _ensure_fresh_token(self) -> str:
        """Refresh access_token if it's close to expiry.

        LinkedIn access tokens last 60 days. We refresh proactively if
        we're within 5 days of expiry. The refresh_token itself lasts
        365 days.
        """
        access = self.credentials.get("access_token", "")
        expires_at = float(self.credentials.get("access_token_expires_at") or 0)
        now = time.time()

        if access and expires_at and expires_at - now > 5 * 86400:
            return access  # still good

        refresh = self.credentials.get("refresh_token", "")
        if not refresh:
            raise AuthError(
                "LinkedIn access_token expired and no refresh_token available. "
                "Re-run: python -m comet_repurposer.cli auth-linkedin"
            )

        body = {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": self.credentials["client_id"],
            "client_secret": self.credentials["client_secret"],
        }
        try:
            resp = requests.post(LINKEDIN_REFRESH_URL, data=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise AuthError(f"refresh network error: {exc}") from exc
        if resp.status_code >= 400:
            raise AuthError(f"refresh failed ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        self.credentials["access_token"] = data["access_token"]
        self.credentials["access_token_expires_at"] = str(now + data.get("expires_in", 5184000))
        if data.get("refresh_token"):
            self.credentials["refresh_token"] = data["refresh_token"]
            self.credentials["refresh_token_expires_at"] = str(now + data.get("refresh_token_expires_in", 31536000))
        return self.credentials["access_token"]


# ---------------------------------------------------------------------------
# Interactive OAuth flow (first-time setup)
# ---------------------------------------------------------------------------

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Capture ?code=... from LinkedIn's redirect."""

    def __init__(self, *args, captured: Dict, ready_event: Event, **kwargs):
        self._captured = captured
        self._ready = ready_event
        super().__init__(*args, **kwargs)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            self._captured["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorized. You can close this tab.</h1>")
        elif "error" in params:
            self._captured["error"] = params.get("error_description", params["error"])[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Authorization failed.</h1>")
        else:
            self.send_response(404)
            self.end_headers()
        self._ready.set()

    def log_message(self, *args):  # silence default logging
        pass


def run_linkedin_oauth_flow(
    client_id: str,
    client_secret: str,
    redirect_port: int = 8080,
    open_browser: bool = True,
    timeout_s: float = 180.0,
) -> Dict[str, str]:
    """Run the LinkedIn OAuth 2.0 dance in a local browser.

    Returns a dict with: access_token, refresh_token, access_token_expires_at,
    refresh_token_expires_at, person_id.
    """
    redirect_uri = f"http://localhost:{redirect_port}/callback"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join([
            "openid", "profile", "email",
            "w_member_social", "r_member_social",
        ]),
        "state": "comet_riobamba",
    }
    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"

    captured: Dict[str, str] = {}
    ready = Event()
    handler = lambda *a, **kw: _OAuthCallbackHandler(
        *a, captured=captured, ready_event=ready, **kw
    )
    server = HTTPServer(("127.0.0.1", redirect_port), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        if open_browser:
            print(f"\nOpening browser to authorize LinkedIn...\n{auth_url}\n")
            try:
                webbrowser.open(auth_url)
            except Exception:
                print(f"Could not open browser. Open this URL manually:\n{auth_url}")
        else:
            print(f"Open this URL manually:\n{auth_url}")

        if not ready.wait(timeout=timeout_s):
            raise AuthError("OAuth flow timed out waiting for callback.")

        if "error" in captured:
            raise AuthError(f"LinkedIn returned error: {captured['error']}")
        if "code" not in captured:
            raise AuthError("No authorization code received.")

        # Exchange code for tokens.
        body = {
            "grant_type": "authorization_code",
            "code": captured["code"],
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        resp = requests.post(LINKEDIN_TOKEN_URL, data=body, timeout=30)
        if resp.status_code >= 400:
            raise AuthError(f"token exchange failed ({resp.status_code}): {resp.text[:300]}")
        tokens = resp.json()

        # Fetch person_id (LinkedIn uses 'sub' field in userinfo).
        me = requests.get(
            LINKEDIN_ME_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=30,
        )
        if me.status_code >= 400:
            raise AuthError(f"userinfo failed: {me.text[:200]}")
        person_id = me.json().get("sub")
        if not person_id:
            raise AuthError("Could not extract person_id (sub) from userinfo")

        now = time.time()
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "access_token_expires_at": str(now + tokens.get("expires_in", 5184000)),
            "refresh_token_expires_at": str(now + tokens.get("refresh_token_expires_in", 31536000)),
            "person_id": person_id,
        }
    finally:
        server.shutdown()
        server.server_close()
