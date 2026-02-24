from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "CRAWLER_", "env_file": ".env"}

    HOST = "127.0.0.1"
    PORT = 8001
    LOG_LEVEL = "INFO"


settings = Settings()
