from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "development"
    api_port: int = 8000
    web_port: int = 5173
    app_origin: str = "http://localhost:5173"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "change-me"
    mysql_database: str = "research_macha"
    database_url: str | None = None

    upload_dir: str = "api/uploads"
    embedding_dim: int = 64
    vector_provider: str = "qdrant"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "research_macha_chunks"
    qdrant_vector_size: int | None = None

    ai_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "gpt-oss:20b-cloud"
    ollama_embed_model: str = "nomic-embed-text"

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @computed_field
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @computed_field
    @property
    def resolved_upload_dir(self) -> Path:
        return ROOT_DIR / self.upload_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
