from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from home_atlas.llm_config import ACTIVE_LLM


AgentMode = Literal["auto", "rules", "ai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOME_ATLAS_", env_file=".env", populate_by_name=True)

    database_url: str = "sqlite:///home_atlas.db"
    token_map: dict[str, str] = Field(default_factory=dict)
    llm_model: str = Field(default="", validation_alias=AliasChoices("llm_model", ACTIVE_LLM.app_model_env))
    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(ACTIVE_LLM.app_api_key_env, ACTIVE_LLM.provider_api_key_env),
    )
    agent_mode: AgentMode = "auto"
    mcp_issuer_url: str = "http://localhost:8080"
    mcp_resource_server_url: str = "http://localhost:8080/mcp"
    host: str = "0.0.0.0"
    port: int = 8080


def get_settings() -> Settings:
    return Settings()
