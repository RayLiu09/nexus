"""Retire only legacy major-distribution governance configuration."""

from copy import deepcopy


RETIRED_CODES = frozenset({"major_distribution", "program_distribution"})


def clean_rules(content):
    """Keep deployment customizations and shared knowledge types intact."""
    result = deepcopy(content)
    result["classifications"] = [
        c for c in result.get("classifications", []) if c.get("code") not in RETIRED_CODES
    ]
    tags = []
    for tag in result.get("tags", []):
        original = tag.get("applicable_classifications")
        if isinstance(original, list) and set(original) & RETIRED_CODES:
            tag["applicable_classifications"] = [c for c in original if c not in RETIRED_CODES]
            if not tag["applicable_classifications"]:
                continue
        tags.append(tag)
    if "tags" in result:
        result["tags"] = tags
    knowledge_types = []
    for entry in result.get("knowledge_types", []):
        original = entry.get("applicable_classifications")
        if isinstance(original, list) and set(original) & RETIRED_CODES:
            entry["applicable_classifications"] = [c for c in original if c not in RETIRED_CODES]
            if not entry["applicable_classifications"]:
                continue
        knowledge_types.append(entry)
    if "knowledge_types" in result:
        result["knowledge_types"] = knowledge_types
    # Some deployments store per-classification policy overrides as keyed maps.
    for name in (
        "classification_rules",
        "quality_rules",
        "tagging_rules",
        "admission_rules",
        "review_rules",
    ):
        policies = result.get(name)
        if isinstance(policies, dict):
            for code in RETIRED_CODES:
                policies.pop(code, None)
    return result


def retired_config(code, scenario=""):
    code, scenario = str(code or "").removeprefix("occupation."), str(scenario or "")
    return any(
        value == name or value.startswith(name + ".") or value.startswith(name + "_")
        for value in (code, scenario)
        for name in RETIRED_CODES
    )


def retire_database_config(bind):
    """Called inside an Alembic transaction; no commits and no history deletion."""
    import json
    from uuid import uuid4
    from sqlalchemy import JSON, bindparam, text

    rows = (
        bind.execute(
            text(
                "SELECT id, version, rules_content FROM governance_rules_version WHERE status = 'active'"
                + (" FOR UPDATE" if bind.dialect.name == "postgresql" else "")
            )
        )
        .mappings()
        .all()
    )
    if len(rows) > 1:
        raise ValueError("multiple active governance rule versions")
    changes = []
    if rows:
        row = rows[0]
        previous = (
            json.loads(row["rules_content"])
            if isinstance(row["rules_content"], str)
            else row["rules_content"]
        )
        content = clean_rules(previous)
        if content != previous:
            bind.execute(
                text(
                    "UPDATE governance_rules_version SET status='archived', updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"id": row["id"]},
            )
            version = bind.execute(
                text("SELECT COALESCE(MAX(version), 0) + 1 FROM governance_rules_version")
            ).scalar_one()
            new_id = str(uuid4())
            bind.execute(
                text(
                    "INSERT INTO governance_rules_version (id, version, status, rules_content, schema_version, change_summary, created_by, trace_id, created_at, updated_at) "
                    "VALUES (:id, :version, 'active', :content, :schema_version, :summary, 'system', 'retire_major_distribution', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ).bindparams(bindparam("content", type_=JSON)),
                {
                    "id": new_id,
                    "version": version,
                    "content": content,
                    "schema_version": content.get("schema_version", "3.0"),
                    "summary": "Retire major-distribution Pipeline B; Ministry API writes domain facts directly",
                },
            )
            changes.extend(
                [
                    (
                        "GovernanceRulesVersionArchived",
                        "governance_rules_version",
                        row["id"],
                        {"successor_id": new_id},
                    ),
                    (
                        "GovernanceRulesVersionCreated",
                        "governance_rules_version",
                        new_id,
                        {"previous_id": row["id"], "version": version},
                    ),
                ]
            )
    prompts = (
        bind.execute(
            text("SELECT id, profile_name, scenario FROM ai_prompt_profile WHERE status='active'")
        )
        .mappings()
        .all()
    )
    for prompt in prompts:
        if retired_config(prompt["profile_name"], prompt["scenario"]):
            bind.execute(
                text(
                    "UPDATE ai_prompt_profile SET status='disabled', updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"id": prompt["id"]},
            )
            changes.append(
                (
                    "PromptProfileDisabled",
                    "ai_prompt_profile",
                    prompt["id"],
                    {"reason": "major_distribution_pipeline_retired"},
                )
            )
    analysis = (
        bind.execute(
            text("SELECT id, rule_set_code, scenario FROM ai_analysis_rules WHERE is_active=true")
        )
        .mappings()
        .all()
    )
    for rule in analysis:
        if retired_config(rule["rule_set_code"], rule["scenario"]):
            bind.execute(
                text(
                    "UPDATE ai_analysis_rules SET is_active=false, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"id": rule["id"]},
            )
            changes.append(
                (
                    "GovernanceRulesUpdated",
                    "ai_analysis_rules",
                    rule["id"],
                    {"reason": "major_distribution_pipeline_retired", "is_active": False},
                )
            )
    for event, target_type, target_id, summary in changes:
        bind.execute(
            text(
                "INSERT INTO audit_log (id, event_type, actor_type, actor_id, target_type, target_id, trace_id, summary, created_at, updated_at) "
                "VALUES (:id, :event, 'system', 'migration_0121', :target_type, :target_id, 'retire_major_distribution', :summary, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ).bindparams(bindparam("summary", type_=JSON)),
            {
                "id": str(uuid4()),
                "event": event,
                "target_type": target_type,
                "target_id": target_id,
                "summary": summary,
            },
        )
    return len(changes)


def has_retired_profile(metadata):
    """Inspect routing metadata only, never infer a route from document prose."""
    if not isinstance(metadata, dict):
        return False
    for key in (
        "domain_profile",
        "classification",
        "classification_code",
        "record_type",
        "schema_version",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and any(
            value == c or value.startswith(c + ".") or value.startswith(c + "_")
            for c in RETIRED_CODES
        ):
            return True
    return any(
        has_retired_profile(metadata.get(k))
        for k in ("profile", "metadata", "metadata_summary", "governance", "record_body", "dataset")
    )
