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
from nexus_app.knowledge_outline.llm_classifier import (
    LLMOutlineOutcome,
    build_and_persist_outline_llm,
    ensure_knowledge_outline_prompt_profile,
)

__all__ = [
    "HeadingInput",
    "OutlineBuildResult",
    "OutlineNodeSpec",
    "build_outline",
    "parse_numbering",
    # v2 LLM path
    "LLMOutlineOutcome",
    "build_and_persist_outline_llm",
    "ensure_knowledge_outline_prompt_profile",
]
