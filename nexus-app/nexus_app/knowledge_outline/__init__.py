"""Knowledge outline construction and persistence.

Deterministic 3-level outline built from MinerU heading trees over
``theory_knowledge`` textbooks. See
``docs/task-packages/wk_conceptual_textbook_knowledge_outline_v1_task_package.md``.
"""

from nexus_app.knowledge_outline.builder import (
    HeadingInput,
    OutlineBuildResult,
    OutlineNodeSpec,
    build_outline,
    parse_numbering,
)

__all__ = [
    "HeadingInput",
    "OutlineBuildResult",
    "OutlineNodeSpec",
    "build_outline",
    "parse_numbering",
]
