"""Strict evidence-bound LiteLLM extraction for institution major profiles."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexus_app.ai_governance.litellm_client import LiteLLMCallError, LiteLLMClientProtocol
from nexus_app.major_profile.schema import validate_profile_payload

MIN_CONFIDENCE = 0.80


@dataclass(frozen=True)
class FallbackResult:
    payload: dict[str, Any] | None
    metadata: dict[str, Any]


class _EvidenceItem(BaseModel):
    """One verbatim field candidate returned by the model."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    source_text: str = Field(min_length=1, max_length=1200)
    evidence_block_ids: list[str] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=MIN_CONFIDENCE, le=1)


class _CourseItem(_EvidenceItem):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=300)


class _Courses(BaseModel):
    model_config = ConfigDict(extra="forbid")

    foundation_courses: list[_CourseItem] = Field(default_factory=list, max_length=30)
    core_courses: list[_CourseItem] = Field(default_factory=list, max_length=30)
    practice_trainings: list[_CourseItem] = Field(default_factory=list, max_length=20)


class _PartnershipItem(_EvidenceItem):
    model_config = ConfigDict(extra="forbid")

    partner_name: str | None = Field(default=None, max_length=300)
    partnership_type: str = Field(default="industry_education", pattern="^(industry_education|school_enterprise|internship_base|unknown)$")


class _InstitutionProfileResponse(BaseModel):
    """The complete, closed JSON contract given to LiteLLM."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    institution_name: str = Field(min_length=2, max_length=300)
    region_tags: list[str] = Field(default_factory=list, max_length=8)
    region_evidence_block_ids: list[str] = Field(default_factory=list, max_length=3)
    major_code: str | None = Field(default=None, pattern=r"^\d{4,6}$")
    major_name: str = Field(min_length=2, max_length=160)
    education_level: str | None = Field(default=None, max_length=80)
    occupation_oriented: list[_EvidenceItem] = Field(default_factory=list, max_length=30)
    courses_and_training: _Courses
    certificates: list[_EvidenceItem] = Field(default_factory=list, max_length=20)
    industry_partnerships: list[_PartnershipItem] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=MIN_CONFIDENCE, le=1)


def extract(payload: dict[str, Any], *, llm_client: LiteLLMClientProtocol | None, model_alias: str | None) -> FallbackResult:
    if llm_client is None or not model_alias:
        return FallbackResult(None, {"strategy": "llm_fallback", "status": "not_adopted", "reason": "llm_unavailable"})
    blocks = [
        {
            "block_id": str(block.get("block_id")),
            "block_type": str(block.get("block_type") or "unknown"),
            "text": str(block.get("text") or block.get("content") or ""),
        }
        for block in payload.get("blocks", [])
        if isinstance(block, dict) and block.get("block_id")
    ]
    if not blocks:
        return FallbackResult(None, {"strategy": "llm_fallback", "status": "not_adopted", "reason": "no_normalized_blocks"})
    try:
        content, summary = llm_client.call(model_alias, [
            {"role": "system", "content": _PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "title": payload.get("title"),
                        # This is one complete normalized document, not a
                        # map/reduce batch. IDs remain stable for evidence.
                        "document_content": _document_content(blocks),
                    },
                    ensure_ascii=False,
                ),
            },
        ], temperature=0.0, max_tokens=6000, response_format={"type": "json_object"})
        candidate = _InstitutionProfileResponse.model_validate(json.loads(content))
    except ValidationError as exc:
        return FallbackResult(None, {
            "strategy": "llm_fallback",
            "status": "not_adopted",
            "reason": "llm_schema_invalid",
            "schema_errors": _validation_error_summary(exc),
        })
    except (LiteLLMCallError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return FallbackResult(None, {"strategy": "llm_fallback", "status": "not_adopted", "reason": f"llm_failed:{type(exc).__name__}"})
    candidate = candidate.model_dump(mode="json")
    if candidate.pop("schema_version", None) != "major_profile.institution_extract.v1":
        return FallbackResult(None, {"strategy": "llm_fallback", "status": "not_adopted", "reason": "llm_schema_version_invalid"})
    candidate.update({"schema_version": "major_profile.v1", "domain": "major", "domain_profile": "major_profile.v1", "profile_source": "institution_profile", "extractor_version": "major_profile_llm_fallback.v1"})
    try:
        adopted, flags = validate_profile_payload(candidate)
    except ValidationError as exc:
        return FallbackResult(None, {
            "strategy": "llm_fallback",
            "status": "not_adopted",
            "reason": "llm_schema_invalid",
            "schema_errors": _validation_error_summary(exc),
        })
    if flags.get("invalid_schema") or adopted.get("confidence", 0) < MIN_CONFIDENCE:
        return FallbackResult(None, {"strategy": "llm_fallback", "status": "not_adopted", "reason": "llm_schema_invalid"})
    adopted, evidence_summary = _retain_verified_evidence(
        adopted,
        {block["block_id"]: block["text"] for block in blocks},
        normalized_title=str(payload.get("title") or ""),
        trusted_title_identity=bool(payload.get("trusted_title_identity")),
    )
    if adopted is None:
        return FallbackResult(None, {
            "strategy": "llm_fallback",
            "status": "not_adopted",
            "reason": "llm_evidence_or_confidence_invalid",
            "evidence_validation": evidence_summary,
        })
    adopted, flags = validate_profile_payload(adopted)
    if flags.get("invalid_schema"):
        return FallbackResult(None, {"strategy": "llm_fallback", "status": "not_adopted", "reason": "llm_schema_invalid"})
    metadata = {
        "strategy": "llm_fallback",
        "version": "major_profile_llm_fallback.v1",
        "model_alias": model_alias,
        "confidence": adopted["confidence"],
        "llm_request_id": summary.request_id,
        "input_hash": summary.input_hash,
        "evidence_validation": evidence_summary,
    }
    adopted["sections"] = _sections_from_profile(adopted)
    adopted["extraction"] = metadata
    return FallbackResult(adopted, metadata)


def _retain_verified_evidence(
    profile: dict[str, Any], source: dict[str, str], *, normalized_title: str = "",
    trusted_title_identity: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """Keep only facts with a verbatim normalized-document citation.

    Models occasionally copy an exact source phrase but attach adjacent heading
    IDs, or attach several IDs even though the phrase belongs to only one
    paragraph.  The model's IDs are therefore treated as a hint, while the
    immutable normalized block text remains the authority.  This function only
    rebinds to exact matching blocks; it never uses fuzzy text matching or
    retains a paraphrase.
    """
    output = dict(profile)
    all_text = "\n".join(source.values())
    institution = str(output.get("institution_name") or "")
    major = str(output.get("major_name") or "")
    institution_from_title = bool(
        trusted_title_identity and institution and _source_matches(institution, normalized_title)
    )
    major_from_title = bool(
        trusted_title_identity and major and _source_matches(major, normalized_title)
    )
    if not (
        institution
        and major
        and (institution_from_title or _source_matches(institution, all_text))
        and (major_from_title or _source_matches(major, all_text))
    ):
        return None, {"verified_items": 0, "discarded_items": 0, "rebound_items": 0}

    verified = 0
    discarded = 0
    rebound = 0

    verified_regions: list[str] = []
    region_ids: list[str] = []
    for tag in output.get("region_tags") or []:
        matches = [block_id for block_id, text in source.items() if isinstance(tag, str) and _source_matches(tag, text)]
        if not matches:
            continue
        verified_regions.append(tag)
        for block_id in matches:
            if block_id not in region_ids:
                region_ids.append(block_id)
    output["region_tags"] = verified_regions
    output["region_evidence_block_ids"] = region_ids

    def retain(items: Any) -> list[dict[str, Any]]:
        nonlocal verified, discarded, rebound
        kept: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                discarded += 1
                continue
            source_text = str(item.get("source_text") or "").strip()
            matches_and_text = [
                (block_id, matched_text)
                for block_id, text in source.items()
                if source_text and (matched_text := _matching_source_text(source_text, text))
            ]
            matches = [block_id for block_id, _ in matches_and_text]
            if not matches:
                discarded += 1
                continue
            claimed = [str(block_id) for block_id in item.get("evidence_block_ids") or []]
            if claimed != matches:
                rebound += 1
            # Preserve the normalized-document spelling as the stored citation.
            kept.append({
                **item,
                "source_text": matches_and_text[0][1],
                "evidence_block_ids": matches,
            })
            verified += 1
        return kept

    output["occupation_oriented"] = retain(output.get("occupation_oriented"))
    output["certificates"] = retain(output.get("certificates"))
    output["industry_partnerships"] = retain(output.get("industry_partnerships"))
    courses = dict(output.get("courses_and_training") or {})
    for key in ("foundation_courses", "core_courses", "practice_trainings"):
        courses[key] = _atomic_course_items(retain(courses.get(key)))
    output["courses_and_training"] = courses

    professional_facts = [
        *output["occupation_oriented"],
        *output["certificates"],
        *output["industry_partnerships"],
        *courses["foundation_courses"],
        *courses["core_courses"],
        *courses["practice_trainings"],
    ]
    if not professional_facts:
        return None, {"verified_items": verified, "discarded_items": discarded, "rebound_items": rebound}
    summary = {
        "verified_items": verified,
        "discarded_items": discarded,
        "rebound_items": rebound,
    }
    if institution_from_title:
        summary["identity_from_normalized_title"] = 1
    if major_from_title:
        summary["major_identity_from_normalized_title"] = 1
    return output, summary


def _source_matches(candidate: str, source_text: str) -> bool:
    return _matching_source_text(candidate, source_text) is not None


def _matching_source_text(candidate: str, source_text: str) -> str | None:
    """Return an actual source substring for a deterministic presentation match."""
    if candidate in source_text:
        return candidate
    for drop_punctuation in (False, True):
        candidate_compact = _compact_for_match(candidate, drop_punctuation=drop_punctuation)
        source_compact, index_map = _compact_source(source_text, drop_punctuation=drop_punctuation)
        if not candidate_compact:
            continue
        start = source_compact.find(candidate_compact)
        if start < 0:
            continue
        end = start + len(candidate_compact) - 1
        return source_text[index_map[start]:index_map[end] + 1]
    return None


def _compact_for_match(value: str, *, drop_punctuation: bool) -> str:
    return "".join(
        normalized
        for char in value
        if not char.isspace()
        for normalized in [unicodedata.normalize("NFKC", char)]
        if not (drop_punctuation and _is_punctuation(normalized))
    )


def _compact_source(value: str, *, drop_punctuation: bool) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(value):
        if char.isspace():
            continue
        normalized = unicodedata.normalize("NFKC", char)
        if drop_punctuation and _is_punctuation(normalized):
            continue
        chars.append(normalized)
        index_map.extend([index] * len(normalized))
    return "".join(chars), index_map


def _is_punctuation(value: str) -> bool:
    return all(unicodedata.category(char).startswith("P") for char in value)


def _validation_error_summary(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"path": ".".join(str(part) for part in error.get("loc", ())), "type": str(error.get("type") or "invalid")}
        for error in exc.errors()[:12]
    ]


def _atomic_course_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Represent one course per row so course-frequency queries are meaningful."""
    atomic: list[dict[str, Any]] = []
    for item in items:
        raw_name = str(item.get("name") or item.get("text") or "").strip()
        source_text = str(item.get("source_text") or "")
        names = [part.strip() for part in raw_name.replace("，", "、").replace(",", "、").replace("；", "、").replace(";", "、").split("、")]
        for name in names:
            name = name.removesuffix("等课程").removesuffix("课程").strip()
            if not name or not _source_matches(name, source_text):
                continue
            atomic.append({**item, "name": name, "text": name})
    return atomic


def _document_content(blocks: list[dict[str, str]]) -> str:
    """Serialize the entire normalized document once with evidence anchors."""
    return "\n\n".join(
        f"[{block['block_id']}] ({block['block_type']})\n{block['text']}"
        for block in blocks
    )


def _sections_from_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Project adopted institution facts into section chunks without inventing text."""
    sections: list[dict[str, Any]] = []
    fields = (
        ("occupation_oriented", "职业定位与就业方向", profile.get("occupation_oriented")),
        ("courses_and_training", "课程与实践实训", [
            item
            for values in (profile.get("courses_and_training") or {}).values()
            if isinstance(values, list)
            for item in values
        ]),
        ("certificates", "职业证书", profile.get("certificates")),
        ("industry_partnerships", "校企合作与产教融合", profile.get("industry_partnerships")),
    )
    for key, title, items in fields:
        if not isinstance(items, list):
            continue
        evidence_ids: list[str] = []
        texts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("source_text") or item.get("text") or item.get("name") or "").strip()
            if text:
                texts.append(text)
            for block_id in item.get("evidence_block_ids") or []:
                if isinstance(block_id, str) and block_id not in evidence_ids:
                    evidence_ids.append(block_id)
        if texts and evidence_ids:
            sections.append({
                "section_key": key,
                "section_title": title,
                "text": "\n".join(texts),
                "source_block_ids": evidence_ids,
            })
    return sections


_PROMPT = '''Return one JSON object only. No markdown, prose, or unknown keys.
Schema version is exactly "major_profile.institution_extract.v1".
Use this closed JSON schema:
{
  "schema_version":"major_profile.institution_extract.v1",
  "institution_name":"verbatim school name",
  "region_tags":["explicit province/city only"],"region_evidence_block_ids":["block-id"],
  "major_code":"4-6 digits or null",
  "major_name":"verbatim major name",
  "education_level":"explicit level or null",
  "occupation_oriented":[{"text":"verbatim","source_text":"verbatim","evidence_block_ids":["block-id"],"confidence":0.80}],
  "courses_and_training":{"foundation_courses":[{"name":"one verbatim course name","text":"same course name","source_text":"verbatim source fragment containing that course","evidence_block_ids":["block-id"],"confidence":0.80}],"core_courses":[],"practice_trainings":[]},
  "certificates":[{"text":"verbatim","source_text":"verbatim","evidence_block_ids":["block-id"],"confidence":0.80}],
  "industry_partnerships":[{"text":"verbatim","source_text":"verbatim","evidence_block_ids":["block-id"],"confidence":0.80,"partner_name":"explicit company name or null","partnership_type":"industry_education|school_enterprise|internship_base|unknown"}],
  "confidence":0.80
}
When `trusted_title_identity` is true, the `title` is controlled file metadata
and may provide the institution name and professional name when the document
body does not repeat them. When false, title is only a hint and must not be
used as identity evidence. The
`document_content` field is the entire normalized professional introduction
supplied in one request. Its `[block-id]` anchors must be used in
`evidence_block_ids`; do not ask for another batch or omit later sections.
Extract only from the supplied title and normalized content. Do not infer, summarize, merge,
or invent any field. Every source_text must be copied verbatim from a supplied
block. For courses, emit one array item per course: name and text must be that
single course name, never a sentence or a comma-separated course list; its
source_text may be the complete original sentence containing the course. Leave
optional arrays empty and use null where evidence does not exist. A missing
national major code is valid for an institution page.'''
