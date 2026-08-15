"""Application settings, loaded from environment / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed access to ClipForge configuration.

    Values are read from environment variables (and a local ``.env`` file when
    present). Naming is case-insensitive, e.g. ``APP_ENV`` -> ``app_env``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "ClipForge"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = True

    # Infrastructure
    database_url: str = (
        "mysql+pymysql://clipforge:clipforge@127.0.0.1:3306/clipforge?charset=utf8mb4"
    )
    redis_url: str = "redis://127.0.0.1:6379/0"

    # HTTP
    cors_origins: str = "http://localhost,http://localhost:5173"

    # Processing
    temp_storage_path: str = "/data/temp"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
