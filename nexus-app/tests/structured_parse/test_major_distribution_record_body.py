"""Explicit legacy routes are refused; the API adapter owns new facts."""
import pytest
from nexus_app.structured_parse.record_body_adapter import project_to_record_body


def test_legacy_major_distribution_projection_is_retired():
    with pytest.raises(ValueError, match="retired"):
        project_to_record_body({"sheets": []}, {"domain_profile": "major_distribution.v1"})
