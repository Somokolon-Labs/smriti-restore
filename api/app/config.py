"""Runtime configuration for the Smriti control plane.

Everything is env-driven so the same image runs locally (SQLite + local files)
and on Render (Neon Postgres + bytea/S3) with no code changes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_name: str = "Smriti API"
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # --- database ---
    database_url: str = "sqlite+aiosqlite:///./local.db"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- storage ---
    storage_backend: Literal["postgres", "local", "s3"] = "local"
    storage_local_dir: str = "./storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""

    # --- auth ---
    # Kept as raw strings: pydantic-settings tries to JSON-decode list-typed
    # fields from dotenv, which breaks on plain comma-separated values.
    worker_api_keys_raw: str = Field(default="", validation_alias="WORKER_API_KEYS")
    admin_api_key: str = ""

    # --- quotas ---
    public_jobs_per_hour: int = 30
    public_jobs_per_day: int = 120
    max_queue_depth: int = 200

    # --- job lifecycle ---
    job_lease_seconds: int = 90
    job_max_attempts: int = 3
    worker_offline_after_seconds: int = 45
    claim_long_poll_seconds: int = 25
    reaper_interval_seconds: int = 15

    # --- retention ---
    image_retention_days: int = 14
    image_max_count: int = 4000
    retention_interval_seconds: int = 900

    # --- limits on user input ---
    max_upload_bytes: int = 25 * 1024 * 1024
    # Sources larger than this are downscaled on upload. Restoration output is
    # scale x these dimensions, so the cap bounds worker VRAM as well as storage.
    max_source_pixels: int = 4_000_000  # ~2000x2000
    max_result_pixels: int = 32_000_000  # 4x of the cap, plus headroom

    # --- privacy ---
    # Uploaded photographs are personal. Sources and results are private by
    # default and deleted sooner than the curated showcase.
    private_retention_hours: int = 48

    # --- cors ---
    cors_origins_raw: str = Field(default="http://localhost:3000", validation_alias="CORS_ORIGINS")

    @property
    def worker_api_keys(self) -> list[str]:
        return _split_csv(self.worker_api_keys_raw)

    @property
    def cors_origins(self) -> list[str]:
        return _split_csv(self.cors_origins_raw)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
