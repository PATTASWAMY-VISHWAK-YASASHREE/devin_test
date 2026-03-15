# GitHub Copilot Proxy

An OpenAI-compatible FastAPI proxy that lets you use GitHub Copilot models (GPT-4o, Claude, Gemini, o1, etc.) in any project — just like you'd use the OpenAI or Gemini API.

## Quick Start

### 1. Install dependencies

```bash
cd copilot-proxy
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and set your PROXY_API_KEY (used to protect the proxy)
```

### 3. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Authenticate with GitHub

**Option A: Device Flow (recommended)**

```bash
# Start the device flow
curl http://localhost:8000/login

# Follow the URL and enter the code, then poll for completion:
curl -X POST http://localhost:8000/login/poll \
  -H "Content-Type: application/json" \
  -d '{"device_code": "YOUR_DEVICE_CODE", "interval": 5, "expires_in": 900}'
```

**Option B: Direct Token**

If you already have a GitHub token (from `gh auth token` or a PAT with Copilot access):

```bash
curl -X POST http://localhost:8000/login/token \
  -H "Content-Type: application/json" \
  -d '{"github_token": "gho_xxxxx"}'
```

Or set it in your `.env`:

```env
GITHUB_TOKEN=gho_xxxxx
```

### 5. Use it like any OpenAI API

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-proxy-api-key",  # The PROXY_API_KEY from your .env
    base_url="http://localhost:8000/v1"
)

# Chat completion
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)

# Streaming
stream = client.chat.completions.create(
    model="claude-sonnet-4.6",
    messages=[{"role": "user", "content": "Write a poem about code"}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## Available Models

| Model | Type |
|-------|------|
| `gpt-4o` | OpenAI |
| `gpt-4.1` | OpenAI |
| `gpt-4.1-mini` | OpenAI |
| `gpt-4.1-nano` | OpenAI |
| `o1` | OpenAI |
| `o1-mini` | OpenAI |
| `o3-mini` | OpenAI |
| `claude-sonnet-4` | Anthropic |
| `claude-sonnet-4.5` | Anthropic |
| `claude-sonnet-4.6` | Anthropic |
| `gemini-2.5-pro` | Google |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completions (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/login` | GET | Start GitHub device flow login |
| `/login/poll` | POST | Poll for login completion |
| `/login/token` | POST | Login with existing GitHub token |
| `/health` | GET | Health check |
| `/docs` | GET | Interactive API docs (Swagger) |

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GITHUB_TOKEN` | GitHub OAuth/PAT token | (empty) |
| `PROXY_API_KEY` | API key clients must use | `changeme` |
| `HOST` | Server bind address | `0.0.0.0` |
| `PORT` | Server port | `8000` |

## How It Works

1. **Authentication**: Uses GitHub's OAuth device flow (same as VS Code Copilot) to get an access token
2. **Token Exchange**: Exchanges the GitHub token for a Copilot API token via `api.github.com/copilot_internal/v2/token`
3. **Proxy**: Forwards OpenAI-format requests to the Copilot API with the required VS Code headers
4. **Caching**: Caches Copilot tokens and auto-refreshes when they expire

The proxy mimics the exact headers that VS Code Copilot Chat sends, so the Copilot API treats requests as coming from a legitimate VS Code instance.

## Using with Other Tools

### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o",
    api_key="your-proxy-api-key",
    base_url="http://localhost:8000/v1"
)
```

### curl

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Requirements

- Python 3.10+
- A GitHub account with Copilot access (Copilot Individual, Business, or Enterprise)
