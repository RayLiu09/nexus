"""M-C.1 / M-C.2 golden retrieval query fixtures."""

import json
from pathlib import Path
from typing import Any

from tests.fixtures.retrieval_golden.fixture_registry import (
    FIXTURE_REGISTRY,
    seed_fixture,
)
from tests.fixtures.retrieval_golden.schema import GoldenQuery


_CASSETTES_DIR = Path(__file__).parent / "llm_cassettes"


def load_cassette(cassette_id: str) -> dict[str, Any]:
    """Load and return the raw cassette JSON dict.  Raises FileNotFoundError
    when the caller referenced a missing cassette; ValueError on malformed
    contents.

    Supported cassette shapes:

    * **M-C.2 (sequential)** — top-level ``intent_content`` (required) +
      optional ``planner_content``.  Consumed in call order by
      ``CassetteLiteLLMClient(responses=...)``.
    * **M-D (keyed)** — top-level ``by_model_alias: dict[str, list[str]]``.
      Consumed by lookup in ``CassetteLiteLLMClient(responses_by_alias=...)``.
      Both shapes may coexist; ``by_model_alias`` takes precedence when
      present (see ``cassette_client_kwargs``).
    """
    path = _CASSETTES_DIR / f"{cassette_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"llm cassette not found: {path}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: cassette must be a JSON object")
    if "intent_content" not in payload and "by_model_alias" not in payload:
        raise ValueError(
            f"{path}: cassette missing both 'intent_content' and 'by_model_alias'"
        )
    return payload


def cassette_responses(cassette_id: str) -> list[str]:
    """Return ordered response strings for the sequential path.

    Preserved for M-C.2 back-compat.  For keyed cassettes prefer
    :func:`cassette_client_kwargs` which returns kwargs suitable for
    ``CassetteLiteLLMClient(**kwargs)``.
    """
    payload = load_cassette(cassette_id)
    if "intent_content" not in payload:
        raise ValueError(
            f"cassette {cassette_id!r}: sequential path requires 'intent_content'; "
            f"use cassette_client_kwargs() for keyed cassettes"
        )
    responses = [payload["intent_content"]]
    planner_content = payload.get("planner_content")
    if planner_content is not None:
        responses.append(planner_content)
    return responses


def cassette_client_kwargs(cassette_id: str) -> dict[str, Any]:
    """Return kwargs suitable for ``CassetteLiteLLMClient(**kwargs)``.

    Chooses the right dispatch mode from the cassette shape:

    * ``by_model_alias`` present → ``{"responses_by_alias": {...}}``
    * else → ``{"responses": [intent, planner?]}``

    Callers can pass the return value straight into
    ``CassetteLiteLLMClient`` without branching on shape.
    """
    payload = load_cassette(cassette_id)
    by_alias = payload.get("by_model_alias")
    if isinstance(by_alias, dict) and by_alias:
        return {"responses_by_alias": by_alias}
    return {"responses": cassette_responses(cassette_id)}


__all__ = [
    "FIXTURE_REGISTRY",
    "GoldenQuery",
    "cassette_responses",
    "cassette_client_kwargs",
    "load_cassette",
    "seed_fixture",
]
