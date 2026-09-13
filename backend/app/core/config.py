"""Application settings. Every secret and endpoint is environment-driven."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="")

    # --- app ---
    app_name: str = "FleetBeat"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)
    api_prefix: str = "/api/v1"

    # --- database ---
    database_url: str = Field(
        default="postgresql+asyncpg://fleetbeat:fleetbeat@127.0.0.1:5432/fleetbeat"
    )
    db_echo: bool = False

    # --- redis ---
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")

    # --- auth ---
    jwt_secret: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    password_min_length: int = 10

    # --- security ---
    failed_login_lock_threshold: int = 5
    failed_login_window_minutes: int = 15

    # --- maps: provider is swappable, never hardwired to one vendor ---
    map_provider: str = Field(default="self_hosted")  # self_hosted|maptiler|mapbox|osm_raster
    map_style_url: str = Field(default="")            # overrides provider when set
    maptiler_key: str = Field(default="")
    mapbox_token: str = Field(default="")
    map_raster_url_template: str = Field(default="")
    map_attribution: str = Field(default="© OpenStreetMap contributors")

    # --- routing: OSRM-compatible provider, falls back to the built-in engine ---
    routing_provider: str = Field(default="builtin")  # builtin|osrm
    osrm_url: str = Field(default="")

    # --- simulation ---
    simulation_enabled: bool = Field(default=True)
    simulation_tick_seconds: float = Field(default=2.0)
    simulation_speed_factor: float = Field(default=6.0)

    # --- telemetry freshness thresholds (seconds) ---
    gps_live_threshold: int = 45
    gps_stale_threshold: int = 300

    # --- AI ---
    ai_provider: str = Field(default="builtin")  # builtin|anthropic
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-5")

    # --- cors ---
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
