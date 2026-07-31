# Textbook QA Golden Fixtures

This fixture set protects runtime textbook answer-context selection. It is
separate from `tests/fixtures/retrieval_golden/queries.jsonl`, which focuses on
retrieval DAG/executor behavior.

Each case in `cases.json` supplies:

- `question`: the natural-language textbook question.
- `section_title`: the source section represented by the fixture chunks.
- `expected_context_mode`: usually `compact_answer`; use `complete_section`
  only when the question asks for full/list-style section content.
- `expected_question_type`: the runtime classifier result expected for compact
  answers.
- `chunks`: ordered section evidence chunks.
- `must_include`: substrings that must appear in rendered Markdown.
- `must_not_include`: substrings that must not appear in rendered Markdown.
- `max_answer_chars`: upper bound for rendered answer length.

The test harness builds runtime `answer_span_context` from these chunks, sends
the context through `MDComposerV2`, and asserts that no LLM call is needed.

Guidelines:

- Do not add topic-specific code to make a single case pass.
- Add cases as generic textbook question patterns: definition, method,
  definition+method, comparison, parameter explanation, procedure, and
  complete-section/list questions.
- Put sibling-topic, exercise, figure, and UI OCR noise in fixtures whenever a
  case is meant to guard answer precision.
