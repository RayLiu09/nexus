from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def root_env_file() -> str:
    return str(Path(__file__).resolve().parents[2] / ".env.dev")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=root_env_file(),
        env_prefix="",
        extra="ignore",
    )

    app_env: str = "dev"
    app_name: str = "NEXUS Platform"
    nexus_env: str = "development"
    log_level: str = "INFO"

    nexus_database_url: str | None = Field(default=None, alias="NEXUS_DATABASE_URL")

    postgres_driver: str = "postgresql"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "nexus_dev"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_ssl_mode: str = "disable"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_ssl: bool = False

    minio_endpoint: str = "http://127.0.0.1:9000"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket_primary: str = "nexus-dev-objects"
    minio_secure: bool = False
    minio_region_name: str = "us-east-1"
    minio_bucket_partition_raw: str = "raw"
    minio_bucket_partition_staging: str = "staging"
    minio_bucket_partition_parsed: str = "parsed"
    minio_bucket_partition_normalized: str = "normalized"
    minio_bucket_partition_export: str = "export"
    minio_bucket_partition_misc: str = "misc"

    rabbitmq_scheme: str = "amqp"
    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = 5672
    rabbitmq_vhost: str = "nexus"
    rabbitmq_username: str = "guest"
    rabbitmq_password: str = "guest"
    rabbitmq_url: str | None = None
    celery_broker_url: str | None = None

    mineru_endpoint: str | None = None
    mineru_use_fake: bool = False
    mineru_timeout: int = 1800
    mineru_health_timeout_seconds: float = 3.0
    worker_pool_enabled: bool = True
    worker_pool_size: int = 1
    worker_poll_interval_seconds: float = 5.0
    worker_lease_seconds: int = 120
    worker_max_concurrent: int = 4

    # Pipeline B feature flags (B1.1 - allow gradual rollout).
    # When disabled, xlsx/csv keep going to Pipeline A (DOCUMENT) — current behavior.
    # When enabled, xlsx/csv route to Pipeline B (RECORD) and require structured_parse
    # (B1.2+) to be available; otherwise the worker will fail the job. Operators
    # should only flip these flags after the full B1 chain is deployed.
    # Env vars (case-insensitive): PIPELINE_B_XLSX_ENABLED / PIPELINE_B_CSV_ENABLED.
    pipeline_b_xlsx_enabled: bool = False
    pipeline_b_csv_enabled: bool = False
    ragflow_endpoint: str | None = None
    ragflow_api_key: str | None = None
    ragflow_timeout: int = 60
    ragflow_kb_name_prefix: str = "nexus-dev"
    ragflow_kb_eager_preload: bool = False
    # RAGFlow expects ``<model_name>@<provider>``. ``bge-m3:latest`` is
    # registered on the dev RAGFlow under the Ollama provider (probed via
    # /v1/llm/my_llms). Override via RAGFLOW_EMBEDDING_MODEL env var per env.
    ragflow_embedding_model: str = "bge-m3:latest@Ollama"
    litellm_endpoint: str | None = None
    litellm_api_key: str | None = None
    litellm_timeout: float = Field(default=30.0, alias="LITELLM_TIMEOUT")
    litellm_retry_attempts: int = Field(default=3, alias="LITELLM_RETRY_ATTEMPTS")
    default_governance_model: str = Field(
        default="gpt-4o-mini",
        alias="DEFAULT_GOVERNANCE_MODEL",
    )
    # LLM alias used by NormalizeService for semantic field extraction and
    # summary generation. When unset, falls back to DEFAULT_GOVERNANCE_MODEL so
    # operators don't need to provision two separate keys in dev.
    default_normalize_model: str | None = Field(
        default=None,
        alias="DEFAULT_NORMALIZE_MODEL",
    )

    # Pipeline B B5 LLM aliases — env-level overrides for prompt profiles
    # whose seeded `litellm_model_alias` (e.g. `internal/job-extract-v1`)
    # may not be accessible under the deployed LiteLLM key. When set, the
    # override is preferred over `ai_prompt_profile.litellm_model_alias`;
    # when unset (default), the seeded alias is used unchanged so prod
    # behavior is unaffected.
    litellm_extraction_model_alias: str | None = Field(
        default=None,
        alias="LITELLM_EXTRACTION_MODEL_ALIAS",
    )
    litellm_body_markdown_model_alias: str | None = Field(
        default=None,
        alias="LITELLM_BODY_MARKDOWN_MODEL_ALIAS",
    )

    # ── Auth (P1 JWT) ──────────────────────────────────────────────────────
    # HS256 symmetric secret. MUST be set in production; an in-memory default is
    # generated only when running tests/dev to avoid breaking conftest setups.
    # The fallback is deliberately ephemeral (different per process) so it cannot
    # be relied on in production.
    jwt_secret: str | None = Field(default=None, alias="NEXUS_JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 900       # 15 min — matches console cookie maxAge
    jwt_refresh_ttl_seconds: int = 604800   # 7 days — matches console cookie maxAge
    jwt_issuer: str = "nexus"

    @computed_field
    @property
    def database_url(self) -> str:
        if self.nexus_database_url:
            return self.nexus_database_url

        driver = self.postgres_driver
        if driver == "postgresql":
            # SQLAlchemy needs a DBAPI-specific driver for runtime connections.
            driver = "postgresql+psycopg"
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        database = quote_plus(self.postgres_db)
        ssl = f"?sslmode={quote_plus(self.postgres_ssl_mode)}" if self.postgres_ssl_mode else ""
        return f"{driver}://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{database}{ssl}"

    @computed_field
    @property
    def effective_rabbitmq_url(self) -> str:
        if self.rabbitmq_url:
            return self.rabbitmq_url
        user = quote_plus(self.rabbitmq_username)
        password = quote_plus(self.rabbitmq_password)
        vhost = quote_plus(self.rabbitmq_vhost)
        return f"{self.rabbitmq_scheme}://{user}:{password}@{self.rabbitmq_host}:{self.rabbitmq_port}/{vhost}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
