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
    contents."""
    path = _CASSETTES_DIR / f"{cassette_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"llm cassette not found: {path}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: cassette must be a JSON object")
    if "intent_content" not in payload:
        raise ValueError(f"{path}: cassette missing 'intent_content'")
    return payload


def cassette_responses(cassette_id: str) -> list[str]:
    """Return the ordered LiteLLM response string(s) for a cassette.

    The list has 1 entry when the case takes the direct-retrieval path
    (planner_content is null), 2 entries otherwise.  The
    ``CassetteLiteLLMClient`` consumes them in call order — the
    orchestrator calls intent first, then (optionally) planner.
    """
    payload = load_cassette(cassette_id)
    responses = [payload["intent_content"]]
    planner_content = payload.get("planner_content")
    if planner_content is not None:
        responses.append(planner_content)
    return responses


__all__ = [
    "FIXTURE_REGISTRY",
    "GoldenQuery",
    "cassette_responses",
    "load_cassette",
    "seed_fixture",
]
