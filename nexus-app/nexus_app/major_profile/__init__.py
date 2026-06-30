"""Pipeline A major_profile extraction and domain-table writer."""

from nexus_app.major_profile.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION, extract
from nexus_app.major_profile.writer import write

__all__ = ["DOMAIN_PROFILE", "EXTRACTOR_VERSION", "extract", "write"]

