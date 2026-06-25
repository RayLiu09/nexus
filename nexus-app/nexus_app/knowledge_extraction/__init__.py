"""Pipeline B knowledge-unit extraction module.

Owns the LLM-driven extraction of skills / tools / certificates / literacy
items from job_demand records (B5.2) and the structuring of free-text task
descriptions on occupational_work_task (B5.4). Body-markdown rendering
lives in a sibling module (`nexus_app/body_markdown/`).

Public surface:
- `load_seed_file` / `seed_ai_analysis_rules` (B5.1 — rules loader)
- `extract_requirements_for_dataset` (B5.2 — extraction service)
- `structure_task_descriptions_for_analysis` (B5.4 — task structuring)
"""
from __future__ import annotations

from nexus_app.knowledge_extraction.rules_loader import (
    SEED_FILE_PATH,
    AnalysisRuleSet,
    load_seed_file,
    seed_ai_analysis_rules,
)
from nexus_app.knowledge_extraction.schemas import (
    ExtractionDatasetResult,
    ExtractionRecordResult,
)
from nexus_app.knowledge_extraction.service import (
    SCENARIO,
    extract_requirements_for_dataset,
)
from nexus_app.knowledge_extraction.task_structuring_service import (
    TaskStructuringResult,
    TaskStructuringTaskResult,
    structure_task_descriptions_for_analysis,
)
from nexus_app.knowledge_extraction.task_structuring_service import (
    SCENARIO as TASK_STRUCTURING_SCENARIO,
)

__all__ = [
    "AnalysisRuleSet",
    "ExtractionDatasetResult",
    "ExtractionRecordResult",
    "SCENARIO",
    "SEED_FILE_PATH",
    "TASK_STRUCTURING_SCENARIO",
    "TaskStructuringResult",
    "TaskStructuringTaskResult",
    "extract_requirements_for_dataset",
    "load_seed_file",
    "seed_ai_analysis_rules",
    "structure_task_descriptions_for_analysis",
]
