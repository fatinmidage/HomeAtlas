from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOME_ATLAS_", env_file=".env")

    database_url: str = "sqlite:///home_atlas.db"
    token_map: dict[str, str] = Field(default_factory=dict)
    llm_model: str = "openrouter:openai/gpt-4.1-mini"
    host: str = "0.0.0.0"
    port: int = 8080


def get_settings() -> Settings:
    return Settings()

