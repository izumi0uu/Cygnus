from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = "cygnus-dev-secret-change-me"
    default_admin_email: str = "admin@cygnus.local"
    default_admin_password: str = "admin123"
    jwt_expire_hours: int = 24
    jwt_algorithm: str = "HS256"


settings = Settings()
