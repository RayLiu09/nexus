# Task Package: Course Textbook Subtype Detection Refinement

## Source Context

- `nexus_app.task_outline.detector`: deterministic textbook subtype detection currently weighs task/project signals strongly.
- `nexus_app.task_outline.extractor` and `orchestrator`: rebuild task outline profiles from normalized document payloads.
- `nexus_app.knowledge_outline.service`: knowledge outline construction is gated by `task_outline_profile.textbook_subtype == "theory_knowledge"`.
- User feedback: project-driven new-form textbooks such as `短视频拍摄与剪辑` can still be theory/concept teaching materials and must not be classified only by "项目"/"任务" keywords.

## Goal

Make course-textbook subtype detection more robust for new-form project-driven textbooks whose surface structure uses projects/tasks but whose content essence is concept, theory, and knowledge explanation. Add optional LiteLLM arbitration over the first normalized blocks for ambiguous or projectized-theory cases.

## Scope

- Refine deterministic scoring and classification in `nexus_app.task_outline.detector`.
- Add an optional LiteLLM-backed subtype arbiter that consumes the first N normalized blocks.
- Wire arbiter injection through extraction and rebuild orchestration.
- Add focused tests with fake LLM clients; no network calls in tests.

## Out Of Scope

- Database migrations or schema changes.
- Knowledge outline build/rebuild execution for existing assets.
- Console/API UI changes.
- Reprocessing existing assets automatically.
- New textbook subtype enum values.

## Forbidden Changes

- Do not make task outline rebuild require LiteLLM by default.
- Do not call LiteLLM directly; use the existing LiteLLM OpenAI-compatible client adapter.
- Do not log raw textbook blocks, prompt text with large source content, or API keys.
- Do not change knowledge outline gate semantics.
- Do not include unrelated current Console/API search-outline fusion changes.

## Deliverables

- `nexus-app/nexus_app/task_outline/detector.py`
- `nexus-app/nexus_app/task_outline/subtype_llm.py`
- `nexus-app/nexus_app/task_outline/extractor.py`
- `nexus-app/nexus_app/task_outline/orchestrator.py`
- `nexus-app/nexus_app/task_outline/__init__.py`
- `nexus-app/nexus_app/config.py`
- Focused tests under `nexus-app/tests/task_outline/`.

## Acceptance

- Project-driven textbooks with strong theory/concept exposition classify as `theory_knowledge` even when project/task labels exist.
- Strong work-task/process textbooks still classify as `training_operation`.
- Optional LLM arbitration can override a low-confidence or ambiguous rule result only when the LLM output is schema-valid and sufficiently confident.
- Invalid or failed LLM arbitration falls back to deterministic detection.
- Tests run offline and do not require network access.
