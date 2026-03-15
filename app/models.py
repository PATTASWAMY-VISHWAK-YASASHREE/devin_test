"""Available GitHub Copilot models and their configurations."""

from typing import Optional

from pydantic import BaseModel


class CopilotModel(BaseModel):
    """A model available through the Copilot proxy."""

    id: str
    name: str
    context_window: int = 128000
    max_tokens: int = 8192


# Models available through GitHub Copilot, derived from:
# - openclaw/src/providers/github-copilot-models.ts
# - pi-mono/packages/ai/src/models.generated.ts
AVAILABLE_MODELS: list[CopilotModel] = [
    # OpenAI models
    CopilotModel(id="gpt-4o", name="GPT-4o", context_window=128000, max_tokens=16384),
    CopilotModel(id="gpt-4.1", name="GPT-4.1", context_window=1047576, max_tokens=32768),
    CopilotModel(id="gpt-4.1-mini", name="GPT-4.1 Mini", context_window=1047576, max_tokens=32768),
    CopilotModel(id="gpt-4.1-nano", name="GPT-4.1 Nano", context_window=1047576, max_tokens=32768),
    CopilotModel(id="o1", name="o1", context_window=200000, max_tokens=100000),
    CopilotModel(id="o1-mini", name="o1-mini", context_window=128000, max_tokens=65536),
    CopilotModel(id="o3-mini", name="o3-mini", context_window=200000, max_tokens=100000),
    # Claude models
    CopilotModel(
        id="claude-sonnet-4", name="Claude Sonnet 4", context_window=200000, max_tokens=64000
    ),
    CopilotModel(
        id="claude-sonnet-4.5", name="Claude Sonnet 4.5", context_window=200000, max_tokens=64000
    ),
    CopilotModel(
        id="claude-sonnet-4.6", name="Claude Sonnet 4.6", context_window=200000, max_tokens=64000
    ),
    # Gemini models
    CopilotModel(
        id="gemini-2.5-pro", name="Gemini 2.5 Pro", context_window=1048576, max_tokens=65536
    ),
]

MODELS_BY_ID: dict[str, CopilotModel] = {m.id: m for m in AVAILABLE_MODELS}


def get_model(model_id: str) -> Optional[CopilotModel]:
    """Look up a model by ID."""
    return MODELS_BY_ID.get(model_id)


def list_models() -> list[CopilotModel]:
    """List all available models."""
    return AVAILABLE_MODELS
