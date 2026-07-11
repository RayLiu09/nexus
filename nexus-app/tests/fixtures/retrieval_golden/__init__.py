"""M-C.1 golden retrieval query fixtures."""

from tests.fixtures.retrieval_golden.fixture_registry import (
    FIXTURE_REGISTRY,
    seed_fixture,
)
from tests.fixtures.retrieval_golden.schema import GoldenQuery

__all__ = ["FIXTURE_REGISTRY", "GoldenQuery", "seed_fixture"]
