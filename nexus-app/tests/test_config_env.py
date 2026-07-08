from nexus_app.config import Settings


def test_env_dev_postgres_values_are_loaded_without_sqlite_fallback():
    settings = Settings()

    assert settings.postgres_host == "10.100.11.182"
    assert settings.postgres_db == "nexus_dev"
    assert settings.postgres_user
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "nexus_dev" in settings.database_url


def test_env_dev_middleware_values_are_loaded():
    settings = Settings()

    assert settings.redis_host == "10.100.11.51"
    assert settings.minio_endpoint == "http://10.100.11.182:9000"
    assert settings.minio_bucket_primary == "nexus-dev-objects"
    assert settings.litellm_endpoint == "http://10.100.11.51:4000"
    assert settings.default_governance_model == "doubao-seed-2-0-lite-260215"
    assert settings.litellm_timeout == 300
    assert settings.litellm_retry_attempts == 3
    assert settings.ragflow_endpoint is None


def test_env_dev_embedding_values_are_loaded():
    settings = Settings()

    assert settings.default_embedding_model == "bge-m3:latest"
    assert settings.default_embedding_dimension == 1024
    assert settings.default_embedding_distance_metric == "cosine"
    assert settings.embedding_batch_size == 32
    assert settings.embedding_timeout == 60.0
    assert settings.effective_embedding_model_alias == "bge-m3:latest"


def test_litellm_embedding_alias_overrides_default_embedding_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_EMBEDDING_MODEL", "default-embedding")
    monkeypatch.setenv("LITELLM_EMBEDDING_MODEL_ALIAS", "gateway/embedding")

    settings = Settings()

    assert settings.default_embedding_model == "default-embedding"
    assert settings.effective_embedding_model_alias == "gateway/embedding"


def test_retrieval_intent_model_falls_back_to_governance_model(monkeypatch):
    monkeypatch.delenv("DEFAULT_RETRIEVAL_INTENT_MODEL", raising=False)

    settings = Settings()

    assert settings.retrieval_intent_confidence_threshold == 0.78
    assert settings.effective_retrieval_intent_model_alias == settings.default_governance_model


def test_retrieval_intent_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DEFAULT_GOVERNANCE_MODEL", "governance-model")
    monkeypatch.setenv("DEFAULT_RETRIEVAL_INTENT_MODEL", "retrieval-intent-model")
    monkeypatch.setenv("RETRIEVAL_INTENT_CONFIDENCE_THRESHOLD", "0.82")

    settings = Settings()

    assert settings.default_retrieval_intent_model == "retrieval-intent-model"
    assert settings.effective_retrieval_intent_model_alias == "retrieval-intent-model"
    assert settings.retrieval_intent_confidence_threshold == 0.82


def test_retrieval_planner_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DEFAULT_RETRIEVAL_PLANNER_MODEL", "retrieval-planner-model")
    monkeypatch.setenv("RETRIEVAL_MAX_SUB_QUERIES", "4")

    settings = Settings(DEFAULT_GOVERNANCE_MODEL="governance-model")

    assert settings.default_retrieval_planner_model == "retrieval-planner-model"
    assert settings.effective_retrieval_planner_model_alias == "retrieval-planner-model"
    assert settings.retrieval_max_sub_queries == 4


def test_retrieval_summary_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DEFAULT_RETRIEVAL_SUMMARY_MODEL", "retrieval-summary-model")

    settings = Settings(DEFAULT_GOVERNANCE_MODEL="governance-model")

    assert settings.default_retrieval_summary_model == "retrieval-summary-model"
    assert settings.effective_retrieval_summary_model_alias == "retrieval-summary-model"
