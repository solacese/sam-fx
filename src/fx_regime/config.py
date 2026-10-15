from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8080
    demo_mode: bool = True
    scenario_tick_seconds: float = 1.0
    incident_store_path: str = ".runtime/incidents.sqlite3"
    investigation_timeout_seconds: float = Field(default=8.0, gt=0)
    enable_external_providers: bool = False
    enable_jev_provider: bool = False

    jev_api_key: str = Field(default="", validation_alias=AliasChoices("JEV_API_KEY", "jev"))
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"
    jev_model: str = "jev-latest"
    jev_timeout_seconds: float = 4.0

    groq_api_key: str = Field(default="", validation_alias=AliasChoices("GROQ_API_KEY", "groq"))
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: float = 8.0

    solace_host: str = ""
    solace_vpn: str = "default"
    solace_username: str = ""
    solace_password: str = ""
    solace_client_id: str = "fx-regime-service"

    detector_baseline_seconds: int = 300
    detector_min_baseline_seconds: int = 30
    detector_persistence_seconds: int = 4
    detector_recovery_seconds: int = 8
    detector_entry_score: float = 3.0
    detector_stressed_score: float = 4.2
    detector_exit_score: float = 1.25


@lru_cache
def get_settings() -> Settings:
    return Settings()
