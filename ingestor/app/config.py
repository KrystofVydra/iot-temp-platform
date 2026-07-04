"""Pydantic-settings configuration for the ingestor.

Settings are read from environment variables (and optionally a local
``.env`` file when running outside Docker). Instantiation is lazy via
``get_settings()`` so importing ``app.*`` modules does not require the
env to be populated.
"""

from __future__ import annotations

from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    MQTT_HOST: str
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str
    MQTT_PASSWORD: str
    MQTT_TOPIC: str = "devices/+/telemetry"
    LOG_LEVEL: str = "INFO"
    # Expo push access token (authenticated Expo Push API). Shared with the
    # backend; the detector uses it to deliver notifications to mobile devices.
    EXPO_ACCESS_TOKEN: str = ""


@cache
def get_settings() -> Settings:
    return Settings()
