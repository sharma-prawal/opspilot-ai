"""Central, typed application configuration.

All runtime knobs (model names, limits, budgets, endpoints) live here and are read from the
environment / ``.env``. Nothing else in the codebase reads ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    opspilot_env: Literal["local", "test", "ci"] = "local"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # PostgreSQL
    db_host: str = "127.0.0.1"
    db_port: int = 5433
    db_name: str = "opspilot"
    test_db_name: str = "opspilot_test"
    db_user: str = "opspilot_app"
    db_password: SecretStr = SecretStr("")
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # Ollama / models
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:8b"
    llm_think: bool = False
    llm_num_ctx: int = Field(default=8192, ge=1024, le=131072)
    llm_num_predict: int = Field(default=1536, ge=16, le=8192)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=180.0, gt=0)
    llm_max_concurrency: int = Field(default=1, ge=1, le=8)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_keep_alive: str = "10m"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dimensions: int = Field(default=1024, ge=32, le=4096)
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    embedding_timeout_seconds: float = Field(default=60.0, gt=0)

    # RAG
    knowledge_dir: Path = REPO_ROOT / "datasets/synthetic/knowledge"
    chunk_max_words: int = Field(default=220, ge=50, le=2000)
    chunk_overlap_words: int = Field(default=40, ge=0, le=500)
    retrieval_top_k: int = Field(default=6, ge=1, le=50)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)

    # Agent policy
    agent_max_tool_calls: int = Field(default=60, ge=1, le=500)
    agent_max_llm_calls: int = Field(default=6, ge=1, le=50)
    agent_max_rounds: int = Field(default=2, ge=1, le=5)
    rca_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    tool_timeout_seconds: float = Field(default=20.0, gt=0)
    max_concurrent_investigations: int = Field(default=1, ge=1, le=8)
    langgraph_strict_msgpack: bool = True

    # MCP
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8765

    # API / security
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    operator_token: SecretStr = SecretStr("")
    action_signing_key: SecretStr = SecretStr("")
    approval_token_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    approval_request_ttl_seconds: int = Field(default=3600, ge=30, le=7 * 86400)

    # Observability
    otel_exporter: Literal["none", "console", "otlp"] = "none"
    otel_exporter_otlp_endpoint: str = "http://127.0.0.1:4317"
    otel_service_name: str = "opspilot-api"

    @field_validator("knowledge_dir", mode="before")
    @classmethod
    def _resolve_knowledge_dir(cls, value: object) -> object:
        if isinstance(value, str) and not Path(value).is_absolute():
            return REPO_ROOT / value
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def database_url(self, *, database: str | None = None, driver: str = "psycopg") -> str:
        """SQLAlchemy URL. ``driver='psycopg'`` works for both sync and async engines."""
        name = database or self.db_name
        pw = self.db_password.get_secret_value()
        return f"postgresql+{driver}://{self.db_user}:{pw}@{self.db_host}:{self.db_port}/{name}"

    def libpq_dsn(self, *, database: str | None = None) -> str:
        """Plain libpq connection string (for psycopg pools / the LangGraph checkpointer)."""
        name = database or self.db_name
        pw = self.db_password.get_secret_value()
        return f"postgresql://{self.db_user}:{pw}@{self.db_host}:{self.db_port}/{name}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
