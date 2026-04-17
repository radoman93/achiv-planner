from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    DATABASE_URL: str
    REDIS_URL: str

    SECRET_KEY: str = Field(default=..., validation_alias="JWT_SECRET")
    ALGORITHM: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    BATTLENET_CLIENT_ID: str = ""
    BATTLENET_CLIENT_SECRET: str = ""
    BATTLENET_REDIRECT_URI: str = ""

    ANTHROPIC_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    LLM_ENRICHMENT_ENABLED: bool = False
    LLM_ENRICHMENT_MODE: str = "live"  # live | dry_run | sample
    LLM_SAMPLE_IDS: str = ""  # comma-separated blizzard_ids used when mode=sample
    LLM_DEFAULT_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_COMPLEX_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_MONTHLY_BUDGET_USD: float = 25.0
    LLM_BUDGET_HARD_STOP_USD: float = 50.0
    LLM_BATCH_MIN_SIZE: int = 20
    LLM_MAX_OUTPUT_TOKENS: int = 2000

    FRONTEND_URL: str = "http://localhost:3000"
    RAW_STORAGE_PATH: str = "/raw_storage"

    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    SENTRY_DSN: Optional[str] = None
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    FLOWER_USER: str = "admin"
    FLOWER_PASSWORD: str = "admin"

    VERSION: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
