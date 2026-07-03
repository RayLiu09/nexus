"""Task Outline domain services for task-operation textbooks."""

from nexus_app.task_outline.schemas import (
    TaskOutlineNodeCreate,
    TaskOutlineNodeRead,
    TaskOutlineProfileCreate,
    TaskOutlineProfileRead,
)
from nexus_app.task_outline.detector import (
    TextbookSubtypeDetection,
    detect_course_textbook_subtype,
)
from nexus_app.task_outline.extractor import (
    TaskOutlineExtraction,
    extract_course_textbook_outline,
)
from nexus_app.task_outline.projector import (
    DOMAIN_MODEL,
    project_profile_to_chunks,
)
from nexus_app.task_outline.service import (
    get_profile_by_ref,
    list_nodes,
    replace_nodes,
    upsert_profile,
)

__all__ = [
    "DOMAIN_MODEL",
    "TaskOutlineNodeCreate",
    "TaskOutlineNodeRead",
    "TaskOutlineExtraction",
    "TaskOutlineProfileCreate",
    "TaskOutlineProfileRead",
    "TextbookSubtypeDetection",
    "detect_course_textbook_subtype",
    "extract_course_textbook_outline",
    "get_profile_by_ref",
    "list_nodes",
    "project_profile_to_chunks",
    "replace_nodes",
    "upsert_profile",
]
