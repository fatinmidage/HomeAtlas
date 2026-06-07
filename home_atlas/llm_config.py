from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    provider_name: str
    app_model_env: str
    provider_api_key_env: str
    app_api_key_env: str


ACTIVE_LLM = LLMConfig(
    provider_name="DeepSeek",
    app_model_env="HOME_ATLAS_LLM_MODEL",
    provider_api_key_env="DEEPSEEK_API_KEY",
    app_api_key_env="HOME_ATLAS_LLM_API_KEY",
)


def resolve_api_key(configured_api_key: str | None) -> str | None:
    return (
        configured_api_key
        or os.getenv(ACTIVE_LLM.app_api_key_env)
        or os.getenv(ACTIVE_LLM.provider_api_key_env)
    )


def has_configured_api_key(configured_api_key: str | None) -> bool:
    return bool(resolve_api_key(configured_api_key))


def export_provider_api_key(configured_api_key: str | None) -> None:
    if api_key := resolve_api_key(configured_api_key):
        os.environ[ACTIVE_LLM.provider_api_key_env] = api_key


def normalize_model_name(model: str) -> str:
    if not model or ":" in model:
        return model
    if model.startswith("deepseek-"):
        return f"deepseek:{model}"
    return model
