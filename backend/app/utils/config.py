from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "anthropic"
    check_in_model: str = ""        # default: claude-haiku-4-5 / gpt-4o-mini
    analysis_model: str = ""        # default: claude-sonnet-4-5 / gpt-4o
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    database_url: str = "sqlite:///./dev.db"
    medblocks_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
