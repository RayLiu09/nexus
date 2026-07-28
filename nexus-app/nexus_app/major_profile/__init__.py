"""Pipeline A major_profile extraction and domain-table writer."""

from nexus_app.major_profile.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION, extract
from nexus_app.major_profile.presentation import (
    MAJOR_PROFILE_CLASSIFICATIONS,
    reconcile_presentation,
)
from nexus_app.major_profile.writer import write

__all__ = [
    "DOMAIN_PROFILE",
    "EXTRACTOR_VERSION",
    "MAJOR_PROFILE_CLASSIFICATIONS",
    "extract",
    "reconcile_presentation",
    "write",
]
