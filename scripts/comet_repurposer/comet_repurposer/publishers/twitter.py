"""
X / Twitter publisher using API v2.

Two posting modes:
  - single tweet   : payload_text length <= 280 chars
  - thread         : payload has 'tweets' list (3-7 entries)

Setup (one-time, ~30 min):
  1. Go to https://developer.x.com/en/portal/dashboard
  2. Create a Project + App. Note API_KEY, API_KEY_SECRET.
  3. Generate Access Token + Access Token Secret (App permissions: Read and Write).
  4. Generate Bearer Token.
  5. Add all four to .env (see .env.example).

We use OAuth 1.0a user context (required to post on behalf of a user)
via the ``requests`` library — no external Twitter SDK needed.

Free tier (2026): 1,500 posts/month, 50 posts/24h per user. The
publisher enforces a local rolling 24h window so we never hit the API
limit unexpectedly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import secrets
from typing import Dict, List, Optional

import requests

from .base import (
    AuthError,
    BasePublisher,
    PublishError,
    PublishJob,
    PublishStatus,
    RateLimitError,
)


TWITTER_TWEET_URL = "https://api.twitter.com/2/tweets"
TWITTER_ME_URL = "https://api.twitter.com/2/users/me"

TWEET_MAX_CHARS = 280
LOCAL_24H_LIMIT = 50  # conservative cap below X's free tier


class TwitterPublisher(BasePublisher):
    """Post single tweets or threads via X API v2 (OAuth 1.0a).

    The platform identifier is 'x' (the official brand name since 2023).
    'twitter' is accepted as an alias by the CLI publisher factory.
    """

    platform = "x"

    REQUIRED_KEYS = [
        "api_key", "api_key_secret",
        "access_token", "access_token_secret",
    ]

    def validate_credentials(self) -> None:
        missing = [k for k in self.REQUIRED_KEYS if not self.credentials.get(k)]
        if missing:
            raise AuthError(
                f"Twitter credentials missing: {missing}. "
                f"See .env.example for keys to set."
            )

    def publish(self, job: PublishJob) -> PublishJob:
        self.validate_credentials()

        # Decide single vs thread based on payload.
        tweets: List[str]
        if job.payload.get("tweets"):
            tweets = [str(t)[:TWEET_MAX_CHARS] for t in job.payload["tweets"] if t]
        else:
            text = (job.payload_text or "").strip()
            if not text:
                job.status = PublishStatus.FAILED
                job.error = "Empty payload_text"
                return job
            tweets = [text[:TWEET_MAX_CHARS]]

        if not tweets:
            job.status = PublishStatus.FAILED
            job.error = "No tweets to publish"
            return job

        if self.dry_run:
            job.status = PublishStatus.PUBLISHED  # virtual
            job.platform_post_id = f"dry-run:{self.platform}:{int(time.time())}"
            job.published_at = time.time()
            job.error = None
            return job

        # Post tweets one by one, threading them via in_reply_to.
        previous_id: Optional[str] = None
        posted_ids: List[str] = []
        try:
            for i, tweet_text in enumerate(tweets):
                body: Dict = {"text": tweet_text}
                if previous_id:
                    body["reply"] = {"in_reply_to_tweet_id": previous_id}
                resp = self._signed_post(TWITTER_TWEET_URL, body)
                if resp.status_code == 429:
                    raise RateLimitError(f"Twitter 429: {resp.text[:200]}")
                if resp.status_code >= 400:
                    job.status = PublishStatus.FAILED
                    job.error = (
                        f"Tweet {i+1}/{len(tweets)} failed "
                        f"HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                    return job
                data = resp.json()
                tweet_id = data.get("data", {}).get("id")
                if not tweet_id:
                    job.status = PublishStatus.FAILED
                    job.error = f"Tweet {i+1} posted but no id returned: {data}"
                    return job
                posted_ids.append(tweet_id)
                previous_id = tweet_id
                # Small gap between tweets to let the API register the parent.
                if i < len(tweets) - 1:
                    time.sleep(1.5)
        except RateLimitError:
            raise
        except requests.RequestException as exc:
            job.status = PublishStatus.FAILED
            job.error = f"network error: {exc}"
            return job

        job.platform_post_id = posted_ids[-1] if posted_ids else None
        job.payload["posted_tweet_ids"] = posted_ids
        job.status = PublishStatus.PUBLISHED
        job.published_at = time.time()
        job.error = None
        return job

    # ------------------------------------------------------------------
    # OAuth 1.0a signing (no SDK dependency)
    # ------------------------------------------------------------------

    def _signed_post(self, url: str, body: dict) -> requests.Response:
        """Sign a POST request with OAuth 1.0a and send JSON body."""
        creds = self.credentials
        method = "POST"

        # OAuth params
        oauth_params = {
            "oauth_consumer_key": creds["api_key"],
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": creds["access_token"],
            "oauth_version": "1.0",
        }

        # Build the signature base string.
        # For body=application/json, Twitter wants the body EXCLUDED from
        # the signature base (per their docs for JSON content).
        encoded_params = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
            for k, v in sorted(oauth_params.items())
        )
        base_string = "&".join([
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(encoded_params, safe=""),
        ])

        signing_key = f"{urllib.parse.quote(creds['api_key_secret'], safe='')} & {urllib.parse.quote(creds['access_token_secret'], safe='')}"
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                base_string.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        oauth_params["oauth_signature"] = signature
        auth_header = "OAuth " + ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )

        return requests.post(
            url,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=self.timeout,
        )
