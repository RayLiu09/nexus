"""Normalize-service: LLM semantic extraction + rule-engine fallback validation.

Public surface:
    - NormalizeService: main entry point for validate-and-enhance pipeline
    - NormalizeSchemasRegistry / get_normalize_schemas_registry: contract registry
    - NormalizeContractError: raised when payload cannot satisfy the contract
"""
from nexus_app.normalize.config_loader import (
    NormalizeSchemasRegistry,
    get_normalize_schemas_registry,
)
from nexus_app.normalize.schemas import (
    NormalizeContract,
    NormalizeResult,
    NormalizeValidationIssue,
)
from nexus_app.normalize.service import NormalizeContractError, NormalizeService

__all__ = [
    "NormalizeContract",
    "NormalizeContractError",
    "NormalizeResult",
    "NormalizeSchemasRegistry",
    "NormalizeService",
    "NormalizeValidationIssue",
    "get_normalize_schemas_registry",
]
