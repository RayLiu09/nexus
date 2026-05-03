from nexus_app.config import Settings


def test_env_dev_postgres_values_are_loaded_without_sqlite_fallback():
    settings = Settings()

    assert settings.postgres_host == "10.100.11.182"
    assert settings.postgres_db == "nexus_dev"
    assert settings.postgres_user == "postgre_normal"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "nexus_dev" in settings.database_url


def test_env_dev_middleware_values_are_loaded():
    settings = Settings()

    assert settings.redis_host == "10.100.11.51"
    assert settings.rabbitmq_host == "10.100.11.182"
    assert settings.rabbitmq_vhost == "nexus"
    assert settings.minio_endpoint == "http://10.100.11.182:9000"
    assert settings.minio_bucket_primary == "nexus-dev-objects"
    assert settings.litellm_endpoint == "http://10.100.11.51:4000"
    assert settings.ragflow_endpoint == "http://10.100.11.182:9380"
