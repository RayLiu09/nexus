from nexus_app.enums import (
    AIAdoptionStatus,
    AssetVersionStatus,
    DataSourceStatus,
    IngestBatchStatus,
    IndexStatus,
    JobStatus,
    PromptProfileStatus,
    RawObjectStatus,
    RuleSetStatus,
)


def values(enum_type):
    return {item.value for item in enum_type}


def test_version_status_contract_values_are_frozen():
    assert values(AssetVersionStatus) == {
        "processing",
        "available",
        "review_required",
        "archived",
        "disabled",
        "failed",
    }


def test_week1_shared_status_values_are_available():
    assert "raw_persisted" in values(IngestBatchStatus)
    assert "checksum_failed" in values(RawObjectStatus)
    assert "dead_lettered" in values(JobStatus)
    assert "stale" in values(IndexStatus)
    assert "auto_adopted" in values(AIAdoptionStatus)
    assert values(RuleSetStatus) == {"active", "disabled"}
    assert "active" in values(PromptProfileStatus)
    assert "draft" not in values(PromptProfileStatus)
    assert "enabled" in values(DataSourceStatus)
