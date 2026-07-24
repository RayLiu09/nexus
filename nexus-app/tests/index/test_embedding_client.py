from __future__ import annotations

import httpx
import pytest

from nexus_app.index.embedding_client import (
    EmbeddingClientError,
    FakeEmbeddingClient,
    LiteLLMEmbeddingClient,
)


def test_fake_embedding_client_is_deterministic():
    client = FakeEmbeddingClient(dimension=4)

    first = client.embed_texts(["同一个文本"], model_alias="fake", expected_dimension=4)
    second = client.embed_texts(["同一个文本"], model_alias="fake", expected_dimension=4)

    assert first.vectors == second.vectors
    assert first.dimension == 4
    assert first.model_alias == "fake"
    assert len(first.input_hashes[0]) == 64


def test_litellm_embedding_client_sends_openai_compatible_request(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            headers={"x-request-id": "req-1"},
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LiteLLMEmbeddingClient(
        endpoint="http://litellm.local/",
        api_key="secret",
        default_model_alias="bge-m3:latest",
        timeout=12.5,
    )

    result = client.embed_texts(["问题一", "问题二"], expected_dimension=3)

    assert captured["url"] == "http://litellm.local/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"] == {
        "model": "bge-m3:latest",
        "input": ["问题一", "问题二"],
        "dimensions": 3,
    }
    assert captured["timeout"] == 12.5
    assert result.vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert result.request_id == "req-1"


def test_litellm_embedding_client_sends_volcengine_typed_text_input(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LiteLLMEmbeddingClient(
        endpoint="http://litellm.local",
        api_key="secret",
        default_model_alias="volcengine/ep-test",
    )

    client.embed_texts(["天很蓝"], expected_dimension=3)

    assert captured["json"] == {
        "model": "volcengine/ep-test",
        "input": [{"type": "text", "text": "天很蓝"}],
        "dimensions": 3,
        "optional_params": {"dimensions": 3},
    }


def test_litellm_embedding_client_omits_optional_params_for_volcengine_vision_model(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LiteLLMEmbeddingClient(
        endpoint="http://litellm.local",
        api_key="secret",
        default_model_alias="volcengine/doubao-embedding-vision-251215",
    )

    client.embed_texts(["天很蓝"], expected_dimension=3)

    assert captured["json"] == {
        "model": "volcengine/doubao-embedding-vision-251215",
        "input": [{"type": "text", "text": "天很蓝"}],
        "dimensions": 3,
    }


def test_litellm_embedding_client_rejects_dimension_mismatch(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": [{"embedding": [0.1, 0.2]}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LiteLLMEmbeddingClient(
        endpoint="http://litellm.local",
        api_key="secret",
        default_model_alias="bge-m3:latest",
    )

    with pytest.raises(EmbeddingClientError, match="dimension mismatch"):
        client.embed_texts(["问题"], expected_dimension=3)


def test_litellm_embedding_client_rejects_response_count_mismatch(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": []},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LiteLLMEmbeddingClient(
        endpoint="http://litellm.local",
        api_key="secret",
        default_model_alias="bge-m3:latest",
    )

    with pytest.raises(EmbeddingClientError, match="count mismatch"):
        client.embed_texts(["问题"], expected_dimension=3)
