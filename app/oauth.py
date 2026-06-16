"""GitHub OAuth Web Application Flow helpers.

Implements stateless CSRF protection via HMAC-signed state tokens and
handles the authorization-code → access-token exchange with GitHub.

Required env vars (set only when OAuth login is desired):
  GITHUB_OAUTH_CLIENT_ID      GitHub OAuth / GitHub App client ID
  GITHUB_OAUTH_CLIENT_SECRET  GitHub OAuth / GitHub App client secret

Optional:
  GITHUB_OAUTH_SECRET_KEY     HMAC key for state tokens (auto-generated per process)
  GITHUB_OAUTH_REDIRECT_URI   Explicit callback URL override (useful behind a proxy)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# ── Configuration (read once at import time) ──────────────────────────────────
GITHUB_OAUTH_CLIENT_ID: str = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET: str = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")

# HMAC signing key — random per process if not explicitly set
_STATE_SECRET: str = os.environ.get("GITHUB_OAUTH_SECRET_KEY", "") or secrets.token_hex(32)
_STATE_MAX_AGE: int = 600  # state tokens expire after 10 minutes


def is_oauth_configured() -> bool:
    """True when both client ID and secret are present."""
    return bool(GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET)


# ── Stateless CSRF state tokens ──────────────────────────────────────────────

def generate_state() -> str:
    """Create a signed, timestamped state token for CSRF protection."""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    payload = f"{ts}:{nonce}"
    sig = hmac.new(
        _STATE_SECRET.encode(), payload.encode(), hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{sig}"


def validate_state(state: str) -> bool:
    """Verify that a state token is authentic and not expired."""
    try:
        parts = state.split(":")
        if len(parts) != 3:
            return False
        ts_str, nonce, sig = parts
        payload = f"{ts_str}:{nonce}"
        expected = hmac.new(
            _STATE_SECRET.encode(), payload.encode(), hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        return time.time() - int(ts_str) <= _STATE_MAX_AGE
    except Exception:
        return False


# ── Authorization URL ─────────────────────────────────────────────────────────

def build_authorize_url(redirect_uri: str, state: str) -> str:
    """Construct the GitHub OAuth authorization URL."""
    params = {
        "client_id": GITHUB_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user",
        "state": state,
        "allow_signup": "false",
    }
    return f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"


# ── Token exchange ────────────────────────────────────────────────────────────

async def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for an access token via GitHub's API.

    Returns a dict with ``access_token``, ``token_type``, ``scope`` on success,
    or ``error`` / ``error_description`` on failure.
    """
    data = urllib.parse.urlencode({
        "client_id": GITHUB_OAUTH_CLIENT_ID,
        "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode()

    req = urllib.request.Request(
        "https://github.com/login/oauth/access_token",
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    loop = asyncio.get_running_loop()
    try:
        resp = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=15),
        )
        return json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("GitHub token exchange failed: %s", exc)
        return {"error": "token_exchange_failed", "error_description": str(exc)}


# ── User info ─────────────────────────────────────────────────────────────────

async def fetch_github_user(access_token: str) -> dict | None:
    """Fetch the authenticated user's profile from the GitHub REST API."""
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "InfraPlayground/1.0",
        },
    )

    loop = asyncio.get_running_loop()
    try:
        resp = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=10),
        )
        return json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("GitHub user info fetch failed: %s", exc)
        return None
