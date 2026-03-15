"""GitHub Copilot Proxy - OpenAI-compatible FastAPI service.

Exposes GitHub Copilot models (GPT-4o, Claude, Gemini, o1, etc.) as a
standard OpenAI-compatible API so you can use them in any project that
supports the OpenAI API format.

Usage:
    1. Run the server: uvicorn app.main:app --reload
    2. Visit /login to authenticate with GitHub
    3. Use /v1/chat/completions and /v1/models like any OpenAI API
"""

from contextlib import asynccontextmanager
from typing import Any, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .auth import (
    complete_login,
    get_copilot_token,
    poll_for_access_token,
    start_device_flow,
)
from .config import settings
from .models import get_model, list_models
from .proxy import build_models_response, proxy_chat_completion


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: try to pre-warm the Copilot token on startup."""
    if settings.github_token:
        try:
            await get_copilot_token()
        except Exception:
            pass  # Will be fetched on first request
    yield


app = FastAPI(
    title="GitHub Copilot Proxy",
    description=(
        "OpenAI-compatible API proxy for GitHub Copilot models. "
        "Authenticate via /login, then use /v1/chat/completions just like the OpenAI API."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str
    content: Union[str, list[Any]]
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stop: Optional[Union[str, list[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint."""
    has_github_token = bool(settings.github_token)
    copilot_ready = False
    if has_github_token:
        try:
            token = await get_copilot_token()
            copilot_ready = token.is_usable()
        except Exception:
            pass
    return {
        "status": "ok",
        "github_token_configured": has_github_token,
        "copilot_ready": copilot_ready,
    }


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "GitHub Copilot Proxy",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "models": "/v1/models",
            "login": "/login",
            "health": "/health",
        },
    }


@app.get("/v1/models")
async def get_models():
    """List available models (OpenAI-compatible format)."""
    models_data = [{"id": m.id, "name": m.name} for m in list_models()]
    return build_models_response(models_data)


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """Create a chat completion (OpenAI-compatible).

    Supports both streaming (SSE) and non-streaming responses.
    Use this endpoint exactly like you would use the OpenAI API.

    Example:
        ```python
        from openai import OpenAI

        client = OpenAI(
            api_key="unused",
            base_url="http://localhost:8000/v1"
        )
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        ```
    """
    # Validate model
    model = get_model(request.model)
    if not model:
        available = [m.id for m in list_models()]
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {request.model}. Available: {available}",
        )

    messages = [msg.model_dump(exclude_none=True) for msg in request.messages]

    try:
        if request.stream:
            generator = await proxy_chat_completion(
                model=request.model,
                messages=messages,
                stream=True,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                top_p=request.top_p,
                stop=request.stop,
                presence_penalty=request.presence_penalty,
                frequency_penalty=request.frequency_penalty,
            )
            return EventSourceResponse(
                _wrap_sse_generator(generator),
                media_type="text/event-stream",
            )
        else:
            result = await proxy_chat_completion(
                model=request.model,
                messages=messages,
                stream=False,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                top_p=request.top_p,
                stop=request.stop,
                presence_penalty=request.presence_penalty,
                frequency_penalty=request.frequency_penalty,
            )
            return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


async def _wrap_sse_generator(generator):
    """Wrap the SSE generator to yield properly formatted events."""
    async for chunk in generator:
        # The chunks already come as SSE-formatted "data: {...}" lines
        # Strip the "data: " prefix if present for EventSourceResponse
        line = chunk.strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                yield {"data": "[DONE]"}
            else:
                yield {"data": data}
        elif line:
            yield {"data": line}


# ---------------------------------------------------------------------------
# Login flow
# ---------------------------------------------------------------------------


@app.get("/login")
async def login_start():
    """Start GitHub OAuth device flow.

    Returns a URL and code for the user to authorize in their browser.
    After authorization, call /login/complete with the device_code.
    """
    try:
        device_info = await start_device_flow()
        return {
            "message": "Visit the URL below and enter the code to authorize.",
            "verification_uri": device_info["verification_uri"],
            "user_code": device_info["user_code"],
            "device_code": device_info["device_code"],
            "expires_in": device_info["expires_in"],
            "interval": device_info["interval"],
            "next_step": (
                f"After authorizing, POST to /login/poll with "
                f'{{"device_code": "{device_info["device_code"]}", '
                f'"interval": {device_info["interval"]}, '
                f'"expires_in": {device_info["expires_in"]}}}'
            ),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


class LoginPollRequest(BaseModel):
    device_code: str
    interval: int = 5
    expires_in: int = 900


@app.post("/login/poll")
async def login_poll(request: LoginPollRequest):
    """Poll for login completion after user authorizes the device code.

    This will block until the user completes authorization or the code expires.
    """
    try:
        github_token = await poll_for_access_token(
            device_code=request.device_code,
            interval=request.interval,
            expires_in=request.expires_in,
        )
        copilot = await complete_login(github_token)
        return {
            "status": "success",
            "message": "Successfully authenticated with GitHub Copilot!",
            "copilot_ready": copilot.is_usable(),
            "base_url": copilot.base_url,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
