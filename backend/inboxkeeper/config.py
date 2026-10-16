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
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    frontend_url: str = "http://localhost:5173"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "inboxkeeper.db"

    @property
    def oauth_redirect_uri(self) -> str:
        # Google only accepts loopback redirects for Desktop clients. The
        # callback is served at the root path, the same as Google's own
        # installed-app helper uses.
        return f"http://127.0.0.1:{self.port}/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
