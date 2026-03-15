"""Proxy layer: forwards OpenAI-compatible requests to GitHub Copilot API.

Translates between the standard OpenAI chat/completions format and the
Copilot API, which uses the same OpenAI-compatible format but requires
special headers and authentication.
"""

import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

import httpx

from .auth import COPILOT_HEADERS, get_copilot_token


async def proxy_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    stream: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    stop: Optional[list[str] | str] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
) -> dict | AsyncGenerator[str, None]:
    """Forward a chat completion request to Copilot API.

    Returns a dict for non-streaming or an async generator of SSE strings for streaming.
    """
    token_info = await get_copilot_token()

    # Build the request body matching OpenAI format
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if top_p is not None:
        body["top_p"] = top_p
    if stop is not None:
        body["stop"] = stop
    if presence_penalty is not None:
        body["presence_penalty"] = presence_penalty
    if frequency_penalty is not None:
        body["frequency_penalty"] = frequency_penalty

    # Build headers matching what VS Code Copilot Chat sends
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "Authorization": f"Bearer {token_info.token}",
        "Openai-Intent": "conversation-panel",
        "X-Request-Id": str(uuid.uuid4()),
        **COPILOT_HEADERS,
    }

    # Check if any message contains image content
    has_images = _has_image_content(messages)
    if has_images:
        headers["Copilot-Vision-Request"] = "true"

    # Determine initiator based on last message role
    last_role = messages[-1].get("role", "user") if messages else "user"
    headers["X-Initiator"] = "agent" if last_role != "user" else "user"

    url = f"{token_info.base_url}/chat/completions"

    if stream:
        return _stream_response(url, headers, body)
    else:
        return await _non_stream_response(url, headers, body)


def _has_image_content(messages: list[dict[str, Any]]) -> bool:
    """Check if any message contains image content parts."""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


async def _non_stream_response(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict:
    """Send a non-streaming request and return the response."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code != 200:
            error_detail = resp.text
            try:
                error_json = resp.json()
                error_detail = json.dumps(error_json)
            except (json.JSONDecodeError, ValueError):
                pass
            raise RuntimeError(f"Copilot API error: HTTP {resp.status_code} - {error_detail}")
        return resp.json()


async def _stream_response(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> AsyncGenerator[str, None]:
    """Stream a response from Copilot API, yielding SSE-formatted strings."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                error_text = ""
                async for chunk in resp.aiter_text():
                    error_text += chunk
                raise RuntimeError(f"Copilot API error: HTTP {resp.status_code} - {error_text}")

            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                # Process complete SSE lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        yield f"{line}\n\n"


def build_models_response(models: list[dict[str, Any]]) -> dict:
    """Build an OpenAI-compatible /v1/models response."""
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "github-copilot",
                "permission": [],
                "root": m["id"],
                "parent": None,
            }
            for m in models
        ],
    }
