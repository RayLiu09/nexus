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
    mineru_timeout: int = 300
    ragflow_endpoint: str | None = None
    ragflow_api_key: str | None = None
    litellm_endpoint: str | None = None
    litellm_api_key: str | None = None

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
