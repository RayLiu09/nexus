# Institution Major Profile LLM Task Package

- **Status**: implementation in progress
- **Date**: 2026-08-20

## Goal

Map national standard professional introductions and institution/official-site
professional introductions into the same evidence-bound `major_profile.v1`
domain model. Institution pages frequently omit the national standard's code
and chapter layout, so they require constrained LLM extraction from the
normalized document.

## Scope

- Extend `major_profile` with institution, regional tags, source format, and
  evidence-bound industry-education cooperation rows.
- Preserve rule extraction for national standard documents.
- Add a LiteLLM fallback for institution profile documents after rule
  extraction cannot produce a profile; accept only schema-valid, verbatim
  evidence-bound outputs above the confidence threshold.
- Run this in Pipeline A normalization, so uploaded files, crawler-acquired
  official-school pages, and WebSearch-acquired pages use the same path.
- Add controlled backfill support for the supplied existing asset IDs.
- Adapt `major_profile_knowledge` criteria and chunks for institution-format
  professional introductions, including cooperation/industry-education facts.

## Guardrails

- Input is only `normalized_document`; raw page/PDF/MinerU output is never
  sent to the domain extractor.
- LLM cannot invent a major code, course, occupation, certificate, institution,
  region, or cooperation partner. Every adopted field has block evidence.
- School profiles may omit a national major code, but require institution name,
  major name, and at least one of occupation/course/cooperation evidence.
- Institution profiles do not require national-template duration, capability,
  certificate, or continuation sections. Their eligible knowledge chunks are
  occupation/employment, course/practice, certificate, and cooperation facts.
- The crawler and WebSearch only acquire into Pipeline A; they do not write
  domain rows themselves.

## Verification

```bash
cd nexus-app
uv run pytest tests/test_major_profile.py
uv run python scripts/rebuild_major_profile_for_ref.py --asset-ids \
  c473156d-1858-4f41-8673-6a23fc110c47,fb30ced2-8e5c-4fc5-8d02-2998a8065899
```
