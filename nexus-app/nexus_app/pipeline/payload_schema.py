"""Versioning for `Job.payload` shape.

A bare `Job.payload` JSON column doesn't tell a worker whether it understands
the data inside. Once a payload field is renamed, added, or has its semantics
changed, queued rows from before the change can silently route to the wrong
pipeline or trip on missing keys.

We tag every job with the schema version of its payload at queue time.
Workers refuse jobs whose version they don't recognize, dead-lettering them
so an operator can decide whether to re-ingest under the new schema.

When changing the payload shape:
  1. Bump `JOB_PAYLOAD_SCHEMA_VERSION` (e.g. "v1" → "v2").
  2. Add the new value to `SUPPORTED_JOB_PAYLOAD_VERSIONS`.
  3. Document the migration policy (drop old/re-ingest/translate) in the
     change PR.
"""
from __future__ import annotations

# Bump on any breaking payload change.
JOB_PAYLOAD_SCHEMA_VERSION = "v1"

# Versions a current worker can execute. Old workers will only have the prior
# value, so add new versions here in the deploy that introduces them and keep
# the prior version in the set during the rolling-window transition.
SUPPORTED_JOB_PAYLOAD_VERSIONS: frozenset[str] = frozenset({"v1"})
