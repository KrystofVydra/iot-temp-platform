"""Pydantic-settings configuration for the backend API.

Settings are read from environment variables (and optionally a local
``.env`` file when running outside Docker). Instantiation is lazy via
``get_settings()``.
"""

from __future__ import annotations

from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    API_TOKEN: str
    LOG_LEVEL: str = "INFO"
    # Comma-separated origins. Kept as a raw string because pydantic-settings v2
    # runs its own JSON parser before validators on list-typed fields, which
    # mangles comma-separated env values.
    CORS_ORIGINS: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@cache
def get_settings() -> Settings:
    return Settings()
