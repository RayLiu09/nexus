# Task Package: Major Profile Classification Recovery

## Goal

Make evidence-rich professional introductions classify as `major_profile`, not
course textbooks, and recover asset `ee2577df-2284-4a5e-a1e7-d61bb580ff9b`.

## Scope

- Classification receives masked content for L1/L2 documents.
- Add explicit `major_profile` priority and `course_textbook` exclusion rules.
- Make the governance decision confidence equal the classification-stage
  confidence rather than an average of unrelated stages.
- Version the active classification prompt and rebuild the target's major
  profile projection, chunks, and index.

## Out Of Scope

- Search query/relevance changes, raw deletion, or changes to L3/L4 masking.

## Acceptance

- A document with major code, duration, training objective, occupational
  orientation, and curriculum is classifiable as `major_profile`.
- High tagging/level confidence cannot raise a weak classification confidence.
- The target emits `major_profile_knowledge` and has an indexed projection.
