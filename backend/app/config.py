import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str
    redis_url: str = "redis://localhost:6379"
    database_url: str = "sqlite+aiosqlite:///./scans.db"
    repos_dir: str = "/data/repos"
    webhook_token: str
    # Каталоги, из которых разрешено сканировать локальный код без git-clone.
    # Несколько путей разделяются `os.pathsep` (':' на Unix, ';' на Windows).
    # Пусто -> сканирование по локальному пути выключено.
    allowed_local_roots: str = ""

    @property
    def local_root_paths(self) -> list[Path]:
        """Разрешённые корни для repo_path, нормализованные в абсолютные пути."""
        roots: list[Path] = []
        for raw in self.allowed_local_roots.split(os.pathsep):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw).expanduser().resolve())
        return roots


settings = Settings()
