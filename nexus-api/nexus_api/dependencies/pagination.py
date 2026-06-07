"""`page` / `pageSize` query-parameter pagination for list endpoints.

The console already sends camelCase `pageSize` on its three currently-paginated
pages (`/assets`, `/api-callers`, `/raw-ledger`), so this dependency adopts
the same casing on the wire and resolves it to snake-case internally.

Bounded by `_MAX_PAGE_SIZE` (100) so a single request can never serialize an
unbounded result set. The previous unbounded list endpoints were a DoS vector
for any tenant that accumulated 10k+ rows.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

_DEFAULT_PAGE = 1
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100
_MAX_PAGE = 10_000


@dataclass(frozen=True)
class Pagination:
    """Resolved pagination window. `offset`/`limit` are derived for SQLAlchemy."""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def pagination_params(
    page: int = Query(_DEFAULT_PAGE, ge=1, le=_MAX_PAGE),
    pageSize: int = Query(  # noqa: N803 — camelCase matches console URL convention
        _DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE, alias="pageSize"
    ),
) -> Pagination:
    return Pagination(page=page, page_size=pageSize)
