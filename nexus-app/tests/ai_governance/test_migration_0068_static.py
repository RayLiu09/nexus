"""Static guards for the alembic migration 0068 (v3.0 tag_taxonomy seed).

Because SQLite can't run migrations that rely on ``gen_random_uuid()`` or
partial unique indexes, we don't exercise ``upgrade()``/``downgrade()`` end-
to-end here.  Instead we assert the file's static invariants — enough to
catch:

* revision chain break (0068 must chase 0067)
* seed_data.py output drifting away from what the migration expects
  (schema_version="3.0", ``tag_taxonomy`` present)
* accidental renaming of the migration's trace_id anchor
  (``seed_0068``), which downgrade() uses to identify its own rows

End-to-end migration runs are expected to happen in CI against Postgres
via ``alembic upgrade head``.
"""

from __future__ import annotations

import importlib


_MIGRATION_MODULE = (
    "alembic.versions.20260709_0068_seed_governance_rules_v3_with_tag_taxonomy"
)


def _load_migration_module():
    # Alembic files are not part of the nexus_app package; they live under
    # nexus-app/alembic/versions/*.  Import them by their file path via the
    # standard alembic runner in CI; in unit tests we resolve via a direct
    # module spec so we don't depend on Alembic's script directory scan.
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]  # nexus-app/
    path = (
        root
        / "alembic"
        / "versions"
        / "20260709_0068_seed_governance_rules_v3_with_tag_taxonomy.py"
    )
    assert path.exists(), f"migration file missing: {path}"

    spec = importlib.util.spec_from_file_location(_MIGRATION_MODULE, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_ids() -> None:
    m = _load_migration_module()
    assert m.revision == "20260709_0068"
    assert m.down_revision == "20260709_0067"
    assert m.branch_labels is None
    assert m.depends_on is None


def test_migration_declares_seed_trace_id() -> None:
    m = _load_migration_module()
    assert m._SEED_TRACE_ID == "seed_0068"


def test_seed_data_output_matches_migration_expectations() -> None:
    """The upgrade() asserts schema_version=='3.0' and tag_taxonomy in the
    output — this test catches a drift between seed_data.py and 0068
    before the migration ever runs against a real DB."""
    from nexus_app.ai_governance.seed_data import build_rules_content

    rules = build_rules_content()
    assert rules["schema_version"] == "3.0"
    assert "tag_taxonomy" in rules
    assert isinstance(rules["tag_taxonomy"], dict)
    assert "types" in rules["tag_taxonomy"]
    assert len(rules["tag_taxonomy"]["types"]) == 7


def test_migration_module_is_importable() -> None:
    """Regression guard: bad Python syntax in the migration file surfaces here
    even if pytest never runs the migration end-to-end."""
    m = _load_migration_module()
    assert callable(m.upgrade)
    assert callable(m.downgrade)
