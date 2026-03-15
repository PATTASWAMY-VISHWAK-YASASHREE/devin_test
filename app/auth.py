"""GitHub Copilot OAuth device flow and token management.

Based on patterns from:
- openclaw/src/providers/github-copilot-auth.ts
- openclaw/src/providers/github-copilot-token.ts
- pi-mono/packages/ai/src/utils/oauth/github-copilot.ts
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from .config import settings

CLIENT_ID = "Iv23liuVgYbLZwlARzsi"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_COPILOT_API_BASE = "https://api.individual.githubcopilot.com"

COPILOT_HEADERS = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}


class CopilotTokenCache:
    """Cached Copilot API token with expiry tracking."""

    def __init__(self, token: str, expires_at: float, updated_at: float, base_url: str):
        self.token = token
        self.expires_at = expires_at
        self.updated_at = updated_at
        self.base_url = base_url

    def is_usable(self) -> bool:
        """Check if token is still valid with 5-minute safety margin."""
        return (self.expires_at - time.time()) > 300

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
            "base_url": self.base_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CopilotTokenCache":
        return cls(
            token=data["token"],
            expires_at=data["expires_at"],
            updated_at=data["updated_at"],
            base_url=data.get("base_url", DEFAULT_COPILOT_API_BASE),
        )


_cached_token: Optional[CopilotTokenCache] = None


def derive_copilot_base_url(token: str) -> str:
    """Extract API base URL from Copilot token's proxy-ep field.

    Token format: tid=...;exp=...;proxy-ep=proxy.individual.githubcopilot.com;...
    Converts proxy.xxx to api.xxx.
    """
    match = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token, re.IGNORECASE)
    if not match:
        return DEFAULT_COPILOT_API_BASE
    proxy_ep = match.group(1).strip()
    if not proxy_ep:
        return DEFAULT_COPILOT_API_BASE
    # Remove protocol prefix if present, then convert proxy.* -> api.*
    host = re.sub(r"^https?://", "", proxy_ep)
    host = re.sub(r"^proxy\.", "api.", host, flags=re.IGNORECASE)
    return f"https://{host}" if host else DEFAULT_COPILOT_API_BASE


def _load_cached_token() -> Optional[CopilotTokenCache]:
    """Load cached token from disk."""
    cache_path = Path(settings.token_cache_path)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
        cached = CopilotTokenCache.from_dict(data)
        if cached.is_usable():
            return cached
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def _save_cached_token(cache: CopilotTokenCache) -> None:
    """Save token cache to disk."""
    cache_path = Path(settings.token_cache_path)
    cache_path.write_text(json.dumps(cache.to_dict(), indent=2))


async def exchange_github_token_for_copilot(github_token: str) -> CopilotTokenCache:
    """Exchange a GitHub access token for a Copilot API token.

    Calls https://api.github.com/copilot_internal/v2/token
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            COPILOT_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {github_token}",
                **COPILOT_HEADERS,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Copilot token exchange failed: HTTP {resp.status_code} - {resp.text}"
            )
        data = resp.json()

    token = data.get("token")
    expires_at = data.get("expires_at")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("Copilot token response missing 'token'")
    if not isinstance(expires_at, (int, float)):
        raise RuntimeError("Copilot token response missing 'expires_at'")

    # GitHub returns unix timestamp in seconds
    expires_at_s = float(expires_at)
    if expires_at_s < 1e10:
        # Already in seconds
        pass
    else:
        # Might be ms, convert
        expires_at_s = expires_at_s / 1000.0

    base_url = derive_copilot_base_url(token)
    cache = CopilotTokenCache(
        token=token,
        expires_at=expires_at_s,
        updated_at=time.time(),
        base_url=base_url,
    )
    _save_cached_token(cache)
    return cache


async def get_copilot_token() -> CopilotTokenCache:
    """Get a valid Copilot API token, refreshing if needed."""
    global _cached_token

    # Try in-memory cache first
    if _cached_token and _cached_token.is_usable():
        return _cached_token

    # Try disk cache
    disk_cached = _load_cached_token()
    if disk_cached:
        _cached_token = disk_cached
        return _cached_token

    # Need to fetch a new token
    github_token = settings.github_token
    if not github_token:
        raise RuntimeError(
            "No GitHub token configured. Run the /login endpoint or set GITHUB_TOKEN."
        )

    _cached_token = await exchange_github_token_for_copilot(github_token)
    return _cached_token


async def start_device_flow() -> dict:
    """Initiate GitHub OAuth device flow. Returns device_code, user_code, verification_uri."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            DEVICE_CODE_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "GitHubCopilotChat/0.35.0",
            },
            json={"client_id": CLIENT_ID, "scope": "read:user"},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"GitHub device code request failed: HTTP {resp.status_code}"
            )
        return resp.json()


async def poll_for_access_token(
    device_code: str, interval: int, expires_in: int
) -> str:
    """Poll GitHub for access token after user authorizes the device code."""
    deadline = time.time() + expires_in
    interval_s = max(1, interval)

    while time.time() < deadline:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                ACCESS_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "GitHubCopilotChat/0.35.0",
                },
                json={
                    "client_id": CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            data = resp.json()

        if "access_token" in data:
            return data["access_token"]

        error = data.get("error", "unknown")
        if error == "authorization_pending":
            await asyncio.sleep(interval_s)
            continue
        if error == "slow_down":
            interval_s += 5
            await asyncio.sleep(interval_s)
            continue
        if error == "expired_token":
            raise RuntimeError("Device code expired. Please restart login.")
        if error == "access_denied":
            raise RuntimeError("Login was cancelled by user.")
        raise RuntimeError(f"Device flow error: {error}")

    raise RuntimeError("Device code expired. Please restart login.")


async def complete_login(github_access_token: str) -> CopilotTokenCache:
    """Complete login by exchanging GitHub token for Copilot token and saving it."""
    global _cached_token
    settings.github_token = github_access_token
    _cached_token = await exchange_github_token_for_copilot(github_access_token)
    return _cached_token
