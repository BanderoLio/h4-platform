from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str
    redis_url: str = "redis://localhost:6379"
    database_url: str = "sqlite+aiosqlite:///./scans.db"
    repos_dir: str = "/data/repos"
    webhook_token: str


settings = Settings()
