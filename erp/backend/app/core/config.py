"""Application settings read from ERP_* environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-only-insecure-secret-key-change-me"
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ERP_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://erp:erp@127.0.0.1:5432/erp_dev"
    secret_key: str = DEFAULT_SECRET_KEY
    access_token_minutes: int = 12 * 60
    storage_dir: Path = Path("storage")
    admin_password: str | None = None
    features: str = ""
    cors_origins: str = ""

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, value: str) -> str:
        # A bare postgresql:// URL would make SQLAlchemy look for psycopg2, which is not installed.
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @field_validator("admin_password")
    @classmethod
    def _blank_password_is_unset(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> Self:
        if self.env == "production" and (
            self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < MIN_SECRET_KEY_LENGTH
        ):
            raise ValueError(
                f"ERP_SECRET_KEY must be set to a random value of at least {MIN_SECRET_KEY_LENGTH} "
                "characters when ERP_ENV=production"
            )
        return self

    @property
    def feature_list(self) -> list[str] | None:
        """Feature names from ERP_FEATURES, or None when discovery is unrestricted."""
        names = [name.strip() for name in self.features.split(",") if name.strip()]
        return names or None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
