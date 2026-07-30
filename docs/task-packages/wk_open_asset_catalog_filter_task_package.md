# Task Package: Open Asset Catalog Domain And Tag Filters

## Goal

Let authenticated upstream API callers discover governed, downloadable data
assets by governance classification (data domain) and content tags.

## Scope

- Extend `GET /open/v1/assets` with optional `domain`, `tag_type`, and `tags`
  filters while retaining existing pagination.
- Read semantic tag matches from `tag_asset_index.tag_embedding` rows targeting
  `normalized_asset_ref`, through the shared tag resolver's L4 matching layer
  using `TAG_EMBEDDING_MODEL` rather than the document embedding model.
- Return the current available version, its raw object ID, normalized ref ID,
  governed tag values, and a stable relative download endpoint. Do not mint a
  presigned URL while listing.
- Add focused Open API regression tests and update the public API contracts.

## Out Of Scope

- Per-route API-key permissions, quotas, changes to org/data-level policy,
  tag taxonomy changes, data backfills, and changes to presigned URL issuance.

## Forbidden Changes

- Do not expose `review_required`, `processing`, `failed`, `archived`, or
  `disabled` asset versions.
- Do not bypass `normalized_asset_ref` as the governance/tag target.
- Do not expose object-storage credentials or embed presigned URLs in list
  results.

## Frozen Contract

- Route: `GET /open/v1/assets?domain=&tag_type=&tags=&is_exact_matched=false&page=&pageSize=`.
- `domain` is the official governance `classification` filter.
- `tags` is a repeated query parameter list. Values are semantic retrieval
  queries and match with `ANY` semantics to maximize asset discovery. Without
  `tag_type`, each value searches all supported tag types; `tag_type` is only
  an optional narrowing condition.
- `is_exact_matched` defaults to `false`. When `true`, tags use normalized
  exact matching and do not invoke the embedding service.
- Every item represents an `available` version and exposes
  `download_url_endpoint` as `/open/v1/raw-objects/{raw_object_id}/download-url`.

## Acceptance

- Domain, semantic tag-only, and combined filters return only matching
  available assets.
- `tag_type` narrows a semantic tag query but is not required for tag matching.
- List results contain no presigned URL and expose a stable download endpoint.
- Existing unfiltered list behavior and focused Open API tests pass.
