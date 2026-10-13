from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INBOXKEEPER_", env_file=".env")

    data_dir: Path = Path.home() / ".inboxkeeper"
    host: str = "127.0.0.1"
    port: int = 8765
    # Origins allowed to call the API. The Vite dev server runs on 5173.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
