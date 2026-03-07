from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "GETDOCS_", "env_file": ".env", "extra": "ignore"}

    HOST: str = "127.0.0.1"
    PORT: int = 8001
    LOG_LEVEL: str = "INFO"
    REDIS_URL: str = "redis://localhost:6379"


settings = Settings()
