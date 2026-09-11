"""Application configuration.

Every value is sourced from the environment (see `.env.example` at the repo
root). Nothing secret is ever hardcoded here - Section 7 of the spec.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "FleetBeat API"
    environment: Literal["local", "dev", "staging", "production"] = "local"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://fleetbeat:fleetbeat@db:5432/fleetbeat"

    # --- Redis / Celery ---
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # --- Auth ---
    jwt_secret_key: str = "change-me-in-env-file"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    # Activation / password-reset links (Section 4a: link is shown in the
    # Platform Admin Console, not emailed, for MVP).
    activation_token_expire_hours: int = 72

    # --- Frontend origin(s) for CORS + link generation ---
    web_app_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    # --- Super admin seed (Section 4a) ---
    superadmin_email: str = "Marwan.mousa5@gmail.com"
    superadmin_name: str = "FleetBeat Platform Admin"
    superadmin_initial_password: str | None = None

    # --- External services ---
    osrm_base_url: str = "http://osrm:5000"
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"

    # --- Simulation engine (Section 6) ---
    simulation_enabled: bool = True
    simulation_tick_seconds: float = 3.0
    #: Chance per vehicle per tick of a harsh-braking / acceleration /
    #: speeding event. Calibrated, not guessed: at a 3s tick and ~50 km/h a
    #: vehicle takes ~2,400 ticks to cover 100 km, so this yields roughly
    #: 3.6 events per 100 km - a plausible rate for a mixed fleet. Set it
    #: much higher and every driver's safety score floors at zero within an
    #: hour, which makes the whole scoring feature look broken.
    simulation_event_probability: float = 0.0015

    # --- Security hardening ---
    failed_login_lockout_threshold: int = 5
    failed_login_lockout_minutes: int = 15

    @field_validator("celery_broker_url", "celery_result_backend", mode="before")
    @classmethod
    def _default_to_redis(cls, v: str | None) -> str | None:
        return v or None

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations synchronously."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
