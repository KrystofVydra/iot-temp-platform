"""Pydantic-settings configuration for the backend API.

Settings are read from environment variables (and optionally a local
``.env`` file when running outside Docker). Instantiation is lazy via
``get_settings()``.
"""

from __future__ import annotations

from functools import cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    API_TOKEN: str
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = []

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        # Pydantic-settings doesn't comma-split list[str] from env by default —
        # do it here so callers can write CORS_ORIGINS=a,b,c instead of JSON.
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@cache
def get_settings() -> Settings:
    return Settings()
