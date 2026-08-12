"""Pipeline A talent-training-plan extraction and persistence."""

from nexus_app.talent_training_plan.extractor import DOMAIN_PROFILE, EXTRACTOR_VERSION, extract
from nexus_app.talent_training_plan.writer import write

__all__ = ["DOMAIN_PROFILE", "EXTRACTOR_VERSION", "extract", "write"]
