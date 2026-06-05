"""FastAPI dependency providers grouped by concern.

Currently exposes:
- `require_user`: JWT-based authentication for the `/internal/v1` router.
- `require_api_caller`: re-exported from `nexus_api.auth` for symmetry.
"""
from nexus_api.auth import require_api_caller
from nexus_api.dependencies.idempotency import require_idempotency_key
from nexus_api.dependencies.user import require_user

__all__ = ["require_api_caller", "require_idempotency_key", "require_user"]
