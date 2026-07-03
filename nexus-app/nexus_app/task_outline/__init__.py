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
    DEFAULT_KNOWLEDGE_TYPE_CODE,
    delete_projected_chunks,
    project_profile_to_chunks,
)
from nexus_app.task_outline.orchestrator import (
    TaskOutlineRebuildResult,
    mark_index_manifest_stale,
    rebuild_task_outline_for_ref,
)
from nexus_app.task_outline.service import (
    get_profile_by_ref,
    list_nodes,
    replace_nodes,
    upsert_profile,
)

__all__ = [
    "DOMAIN_MODEL",
    "DEFAULT_KNOWLEDGE_TYPE_CODE",
    "TaskOutlineNodeCreate",
    "TaskOutlineNodeRead",
    "TaskOutlineExtraction",
    "TaskOutlineProfileCreate",
    "TaskOutlineProfileRead",
    "TaskOutlineRebuildResult",
    "TextbookSubtypeDetection",
    "detect_course_textbook_subtype",
    "delete_projected_chunks",
    "extract_course_textbook_outline",
    "get_profile_by_ref",
    "list_nodes",
    "mark_index_manifest_stale",
    "project_profile_to_chunks",
    "rebuild_task_outline_for_ref",
    "replace_nodes",
    "upsert_profile",
]
