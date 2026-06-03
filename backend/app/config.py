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
    LOG_LEVEL: str = "INFO"
    # Comma-separated origins. Kept as a raw string because pydantic-settings v2
    # runs its own JSON parser before validators on list-typed fields, which
    # mangles comma-separated env values.
    CORS_ORIGINS: str = ""
    # Used to build invitation and password-reset URLs returned to clients.
    FRONTEND_ORIGIN: str = "https://app.otti.cz"
    # While True, /auth/forgot-password returns the reset URL in the response
    # body so an operator can hand-deliver it. Flip to False once outbound
    # email is wired up (Phase 6 Round 3).
    EXPOSE_AUTH_LINKS: bool = True
    # bcrypt cost factor. 12 is the modern default; ~250ms per hash on a
    # mid-grade CPU.
    BCRYPT_ROUNDS: int = 12
    # Coolify resource label used to locate the running Mosquitto container
    # from inside the SSH command admins paste on the VPS to provision
    # device credentials. Override in env if the resource is renamed.
    MOSQUITTO_RESOURCE_NAME: str = "iot-mosquitto"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@cache
def get_settings() -> Settings:
    return Settings()
