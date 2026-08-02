from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "anthropic"
    check_in_model: str = ""
    analysis_model: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    database_url: str = "sqlite:///./dev.db"
    medblocks_api_key: str = ""
    medblocks_fhir_base_url: str = ""
    medblocks_fhir_bearer_token: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_postgres_scheme(cls, v: object) -> object:
        # Railway (and some other providers) supply postgres:// URLs.
        # SQLAlchemy 2.0 requires postgresql://.
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
