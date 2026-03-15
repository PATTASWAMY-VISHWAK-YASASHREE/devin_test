"""Configuration for the GitHub Copilot Proxy service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    github_token: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    token_cache_path: str = "copilot_token_cache.json"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
