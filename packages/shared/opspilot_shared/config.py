"""Central, typed application configuration.

All runtime knobs (model names, limits, budgets, endpoints) live here and are read from the
environment / ``.env``. Nothing else in the codebase reads ``os.environ`` directly.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


def default_upload_dir() -> Path:
    """Shared, worktree-independent storage for raw uploaded files: ``$XDG_DATA_HOME/opspilot/uploads``, else
    ``~/.local/share/opspilot/uploads``. Every checkout and worktree of the repository resolves the same directory,
    so a file stored by one API process can be found and deleted by another."""
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local" / "share"
    return base / "opspilot" / "uploads"


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
    # Least-privilege roles for the MCP server processes (audit suspected risk / C0 item O). Provisioned by
    # scripts/db-roles.sh; when no password is configured the children fall back to the application role.
    mcp_read_db_user: str = "opspilot_mcp_read"
    mcp_read_db_password: SecretStr = SecretStr("")
    mcp_actions_db_user: str = "opspilot_mcp_actions"
    mcp_actions_db_password: SecretStr = SecretStr("")
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # Ollama / models
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3.5:9b-q4_K_M"  # preferred tested model (v0.4); qwen3:8b is the supported fallback
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
    embedding_max_concurrency: int = Field(default=2, ge=1, le=16)  # in-flight /api/embed requests per process

    # RAG
    knowledge_dir: Path = REPO_ROOT / "datasets/synthetic/knowledge"
    chunk_max_words: int = Field(default=220, ge=50, le=2000)
    chunk_overlap_words: int = Field(default=40, ge=0, le=500)
    retrieval_top_k: int = Field(default=6, ge=1, le=50)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)

    # Uploaded incident evidence (v0.5): raw files are kept locally for provenance; `opspilot uploads purge` deletes
    # uploaded incidents older than the retention period (their files, normalized records and investigations).
    # v0.9.1: an absolute directory outside the Git checkout by default (see default_upload_dir). An explicit absolute
    # or ~ path is used as is; a relative value keeps its old meaning (relative to this checkout) for compatibility.
    upload_dir: Path = Field(default_factory=default_upload_dir)
    upload_retention_days: int = Field(default=14, ge=1, le=3650)

    # Connected observability (v0.6): optional, read-only Loki and Prometheus connectors. A connector exists only
    # when its URL is set; OpsPilot contacts no other destination. Credentials are never returned by the API.
    loki_url: str = ""
    loki_tenant_id: str = ""  # X-Scope-OrgID for multi-tenant Loki (Grafana Enterprise Logs, Grafana Cloud user ID)
    loki_bearer_token: SecretStr = SecretStr("")
    loki_username: str = ""
    loki_password: SecretStr = SecretStr("")
    loki_service_label: str = "service_name"
    prometheus_url: str = ""
    prometheus_bearer_token: SecretStr = SecretStr("")
    prometheus_username: str = ""
    prometheus_password: SecretStr = SecretStr("")
    prometheus_service_label: str = "service"
    # v0.9 Datadog (read-only). Keys stay backend-only (never NEXT_PUBLIC_*, never in API responses or snapshots).
    datadog_enabled: bool = False
    datadog_site: str = "datadoghq.com"  # one of opspilot_shared.connectors.datadog.SITES
    datadog_api_key: SecretStr = SecretStr("")
    datadog_app_key: SecretStr = SecretStr("")  # application key with logs_read_data, timeseries_query, apm_read
    datadog_env: str = ""  # optional env tag added to every query (e.g. prod)
    datadog_log_indexes: str = ""  # optional comma-separated log indexes (default: all)
    datadog_max_spans: int = Field(default=500, ge=10, le=2000)  # per span query
    datadog_local_api_url: str = ""  # synthetic fixture only; loopback addresses only
    telemetry_templates_file: Path | None = None  # extra/overriding query templates (JSON), see docs
    telemetry_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    telemetry_max_window_hours: float = Field(default=6.0, gt=0, le=24)
    telemetry_max_log_lines: int = Field(default=2000, ge=10, le=5000)  # per Loki query
    telemetry_max_series: int = Field(default=20, ge=1, le=200)  # per Prometheus query
    telemetry_max_response_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024)

    # Agent policy
    agent_max_tool_calls: int = Field(default=60, ge=1, le=500)
    agent_max_llm_calls: int = Field(default=6, ge=1, le=50)
    agent_max_rounds: int = Field(default=2, ge=1, le=5)
    rca_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    tool_timeout_seconds: float = Field(default=20.0, gt=0)
    max_concurrent_investigations: int = Field(default=1, ge=1, le=8)
    # Admission bound: graph segments running + waiting for a slot. Beyond it, new work is refused (HTTP 429)
    # instead of accumulating unbounded waiting tasks (C0 item P).
    max_pending_investigations: int = Field(default=4, ge=1, le=64)
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
    command_lease_seconds: float = Field(default=120.0, gt=0, le=3600)  # redeliver stale in-flight commands
    run_lease_seconds: float = Field(default=60.0, gt=0, le=3600)  # execution ownership lease, renewed while running
    # C0-G4 single execution owner per database (PostgreSQL advisory lock): how long start-up waits for a previous
    # owner (reload / crash being reaped) and how often the held lock is probed.
    execution_owner_acquire_timeout_seconds: float = Field(default=10.0, ge=0, le=300)
    execution_owner_check_seconds: float = Field(default=5.0, gt=0, le=300)

    # Observability
    otel_exporter: Literal["none", "console", "otlp"] = "none"
    otel_exporter_otlp_endpoint: str = "http://127.0.0.1:4317"
    otel_service_name: str = "opspilot-api"

    @field_validator("knowledge_dir", "upload_dir", "telemetry_templates_file", mode="before")
    @classmethod
    def _resolve_knowledge_dir(cls, value: object, info: ValidationInfo) -> object:
        if value == "" and info.field_name == "telemetry_templates_file":
            return None
        if info.field_name == "upload_dir":
            if value in ("", None):
                return default_upload_dir()  # UPLOAD_DIR= (empty) means the shared default, never the cwd
            if isinstance(value, str) and value.startswith("~"):
                return Path(value).expanduser()
        if isinstance(value, str) and value and not Path(value).is_absolute():
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
    # MCP server children are started with an explicit, minimal environment and must not read the secrets in
    # .env behind it (C0 item O). This is the only place that consults os.environ for configuration loading.
    import os

    if os.environ.get("OPSPILOT_NO_DOTENV") == "1":
        return Settings(_env_file=None)  # type: ignore[call-arg]
    return Settings()
