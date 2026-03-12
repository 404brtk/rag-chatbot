from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "GETDOCS_", "env_file": ".env", "extra": "ignore"}

    HOST: str = "127.0.0.1"
    PORT: int = 8001
    LOG_LEVEL: str = "DEBUG"
    REDIS_URL: str = "redis://localhost:6379"
    BOT_NAME: str = "get-docs"
    USER_AGENT: str = "get-docs/0.1.0"
    GITHUB_TOKEN: str | None = None


settings = Settings()
