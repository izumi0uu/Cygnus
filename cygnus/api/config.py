from __future__ import annotations

from secrets import token_urlsafe
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="CYGNUS_",
    )

    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str | None = None
    seed_default_admin: bool = False
    default_admin_email: str | None = None
    default_admin_password: str | None = None
    jwt_expire_hours: int = 24
    jwt_algorithm: str = "HS256"
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def validate_cors_allowed_origins(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return ()
            if raw.startswith("["):
                return value
            return tuple(part.strip() for part in raw.split(",") if part.strip())
        return value

    @model_validator(mode="after")
    def validate_security_defaults(self) -> "Settings":
        if not self.secret_key:
            if self.app_env == "production":
                raise ValueError("CYGNUS_SECRET_KEY is required when CYGNUS_APP_ENV=production")
            self.secret_key = token_urlsafe(48)

        if self.seed_default_admin:
            if not self.default_admin_email or not self.default_admin_password:
                raise ValueError(
                    "CYGNUS_DEFAULT_ADMIN_EMAIL and CYGNUS_DEFAULT_ADMIN_PASSWORD are required when "
                    "CYGNUS_SEED_DEFAULT_ADMIN=true"
                )

        return self


settings = Settings()
