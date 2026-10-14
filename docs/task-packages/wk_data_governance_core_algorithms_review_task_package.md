# Task Package: Data Governance Core Algorithms Technical Review Deck

## Source Context

- `ARCHITECT.md`: normalized-asset governance boundary, AI guardrails, version-state admission, Knowledge Pipeline ownership, semantic retrieval, and evidence-grounded graph contracts.
- `SPEC.md`: P0 governance, quality, traceability, retrieval, and acceptance requirements.
- `WORKFLOWS.md`: bounded documentation task, AI Governance Gate, Semantic Retrieval Integration Gate, and Acceptance Gate.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: governance explanation, quality-score presentation, decision trail, and source citation baseline.
- Current implementation under `nexus-app/nexus_app/normalize`, `ai_governance`, `knowledge`, `domain_normalize`, and `evidence_graph`.

## Goal

Produce slide-ready technical review documents that explain the end-to-end NEXUS data-asset governance algorithms, integrate justified NLP enhancements, and make implementation boundaries and review decisions explicit. The v4.0 HTML remains within the v3.0 eight-part structure and uses 17 pages after adding focused density/annotation and seven-dimensional tagging pages.

## Scope

- Data cleaning, deduplication, and normalization algorithms.
- Parser/component routing and selection rationale for PDF, Office, HTML, Markdown, and structured records.
- A comprehensive NEXUS-scope inefficient-data taxonomy and the full cleaning decision flow.
- AI governance quality evaluation and state-admission algorithms.
- RAG semantic chunking and chunk-quality evaluation algorithms.
- Per-data-type RAG strategies and explicit domain-model structures/algorithms.
- Data-asset domain knowledge modeling and evidence-grounded graph algorithms.
- Current intelligent retrieval path compared with traditional single-path semantic vector recall.
- Proposed production Chinese NLP path: existing deterministic rules + HanLPAdapter + domain dictionaries + BGE + LiteLLM.
- Structured-quality path: Pydantic/domain validators with optional Pandera/Great Expectations, without over-platforming P0.
- Current implementation thresholds, traceability invariants, risks, and review questions.

## Out Of Scope

- Runtime code, database schema, migrations, API behavior, UI behavior, or configuration changes.
- A new governance algorithm implementation.
- Installing or wiring HanLP, Pandera, Great Expectations, spaCy, or NLTK at runtime.
- Productionizing reserved Knowledge Pipelines 2-5.
- Changing the NEXUS architecture or product contract.

## Forbidden Changes

- Do not make raw files, raw JSON, or MinerU raw output governance inputs.
- Do not move governance results away from `normalized_asset_ref`.
- Do not let AI output bypass schema, whitelist, redaction, rules, confidence, or state-machine checks.
- Do not make RAGFlow the owner of NEXUS chunks or introduce an NEXUS LLM gateway.
- Do not present proposal-stage algorithms as already implemented.

## Deliverables

- `docs/NEXUS数据资产治理核心算法技术评审.md`, separated into at most 15 slide pages.
- `docs/NEXUS数据资产治理核心算法v3.0.html`, a self-contained 15-section visual document derived from the v2.0 structure, with final component-integrated implementations and graphical process flows.
- `docs/NEXUS数据资产治理核心算法v4.0.html`, a self-contained 17-section refinement of v3.0 with format-specific inefficient-data rules, a repository-grounded density example, an NLP Annotation example, HanLP/domain-dictionary/LLM classification and tagging collaboration, seven-dimensional tag implementation details, readable quality-veto wording, corrected Pipeline B business data types, and fully annotated semantic-boundary features.
- Source and implementation references sufficient for reviewers to verify each algorithm.

## Acceptance

- Page count is at most 15 when split on Markdown horizontal-rule page breaks.
- All eight requested review sections are covered with detailed processing steps, formulas, component choices, and trade-offs.
- Current behavior and recommended enhancements are visibly distinguished.
- The v3.0 HTML presents the selected target implementation directly, omits proposal-status wording and non-selected alternatives, removes uploaded HTML from the main parser routes, and names invariants consistently as constraint boundaries.
- Every process-oriented sequence in the v3.0 HTML is rendered as an HTML/CSS flow, branch, or timeline rather than a plain-text arrow diagram.
- Mandatory NEXUS governance, lineage, knowledge-pipeline, and state contracts are preserved.
- A reviewer can identify the formulas, thresholds, failure routes, observability metrics, and decisions requiring approval.
- The v4.0 inefficient-data taxonomy identifies applicable formats per rule and distinguishes crawler HTML from uploaded documents.
- The v4.0 density example uses NEXUS job-demand or major-distribution domain data and shows numerator features, token count, score, threshold, and disposition.
- The v4.0 NLP Annotation example preserves original-text offsets and demonstrates HanLP output, domain-dictionary normalization, downstream feature use, and evidence immutability.
- The v4.0 RAG registry uses NEXUS business-domain type names for Pipeline B records, removes the unsupported QA route, and explains every term in the semantic boundary formula.
- The v4.0 classification path explains how structural evidence, HanLP Annotation, business-expert domain dictionaries, and constrained LiteLLM decisions produce an auditable classification result, including the dictionary-miss fallback.
- The v4.0 tagging path defines all seven dimensions (`regions`, `industries`, `occupations`, `majors`, `abilities`, `topics`, `time_ranges`) and shows candidate generation, business-expert dictionary matching, semantic adjudication, confidence fusion, adoption, review, and rejection; domain dictionary ownership remains with business experts.
- The v4.0 HTML has 17 numbered sections, remains self-contained, and keeps all process sequences graphical.
