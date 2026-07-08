"""`/internal/v1` package — console control-plane API.

This package assembles the JWT-gated main `router` (mounted at `/internal/v1`)
from the per-domain sub-routers. Auth (`/internal/v1/auth/*`) lives on a
separate `auth_router` so it can opt out of the parent's `require_user`
dependency — FastAPI does not let a decorator-level `dependencies=[]`
override the router-level deps, so the auth endpoints must be a sibling
router.

Handler symbols are re-exported from each sub-module so existing call sites
that import them directly (e.g. tests that invoke `runtime_state`,
`create_multi_raw_batch`, `submit_ingest_file`) keep working without
touching test code.
"""
from fastapi import APIRouter, Depends

from nexus_api.dependencies import require_user

# Sub-routers — one per domain.
from nexus_api.api.internal.system import router as _system_router
from nexus_api.api.internal.identity import router as _identity_router
from nexus_api.api.internal.data_sources import router as _data_sources_router
from nexus_api.api.internal.ingest import router as _ingest_router
from nexus_api.api.internal.jobs import router as _jobs_router
from nexus_api.api.internal.assets import router as _assets_router
from nexus_api.api.internal.ai_prompts import router as _ai_prompts_router
from nexus_api.api.internal.ai_governance import router as _ai_governance_router
from nexus_api.api.internal.governance import router as _governance_router
from nexus_api.api.internal.governance_prompts import router as _governance_prompts_router
from nexus_api.api.internal.normalized_refs import router as _normalized_refs_router
from nexus_api.api.internal.record_assets import router as _record_assets_router
from nexus_api.api.major_profiles import internal_router as _major_profiles_router
from nexus_api.api.internal.capability_graph_staging import (
    router as _capability_graph_staging_router,
)
from nexus_api.api.internal.evidence_graph import router as _evidence_graph_router
from nexus_api.api.internal.task_outline import router as _task_outline_router
from nexus_api.api.internal.knowledge_retrieval import router as _knowledge_retrieval_router

# Auth router — separate top-level mount, no shared deps.
from nexus_api.api.internal.auth import router as auth_router

# Re-export handler symbols so call sites that imported them off the old
# flat `internal.py` keep working (tests in particular use this pattern).
from nexus_api.api.internal.system import runtime_state  # noqa: F401
from nexus_api.api.internal.auth import (  # noqa: F401
    auth_login,
    auth_refresh,
    auth_logout,
)
from nexus_api.api.internal.identity import (  # noqa: F401
    create_org_unit,
    list_org_units,
    get_org_unit,
    create_user,
    list_users,
    get_user,
    create_api_caller,
    list_api_callers,
    get_api_caller,
    revoke_api_caller,
)
from nexus_api.api.internal.data_sources import (  # noqa: F401
    create_data_source,
    list_data_sources,
    get_data_source,
    delete_data_source,
    create_data_source_scan_task,
)
from nexus_api.api.internal.ingest import (  # noqa: F401
    create_multi_raw_batch,
    append_file_to_batch,
    submit_ingest_multi_file,
    submit_ingest_file,
    submit_ingest_file_upload,
    submit_crawler_package,
    list_ingest_batches,
    get_ingest_batch,
    list_raw_objects_for_batch,
    list_raw_objects,
    get_raw_object,
)
from nexus_api.api.internal.jobs import (  # noqa: F401
    list_jobs,
    get_job,
    list_job_stages,
    retry_job,
    cancel_job,
    list_parse_artifacts,
    list_normalized_refs,
    list_audit_logs,
)
from nexus_api.api.internal.assets import (  # noqa: F401
    list_assets,
    get_asset,
    list_asset_versions,
    restart_governance_for_version,
)
from nexus_api.api.internal.ai_prompts import (  # noqa: F401
    create_prompt_profile,
    list_prompt_profiles,
    get_prompt_profile,
    update_prompt_profile,
    disable_prompt_profile,
    dry_run_prompt_profile,
)
from nexus_api.api.internal.ai_governance import (  # noqa: F401
    create_governance_run,
    list_governance_runs,
    get_governance_run,
    get_governance_run_quality_summary,
)
from nexus_api.api.internal.governance import (  # noqa: F401
    get_governance_result,
    get_governance_result_for_ref,
    get_governance_rules,
    update_governance_rules,
    reload_governance_rules,
    recompute_governance_rules,
    list_governance_rules_versions,
    get_governance_rules_version,
)
from nexus_api.api.internal.governance_prompts import (  # noqa: F401
    list_prompt_templates,
    get_prompt_template,
    update_prompt_template,
    disable_prompt_template,
)
from nexus_api.api.internal.knowledge_retrieval import (  # noqa: F401
    preview_knowledge_retrieval_plan,
    run_knowledge_retrieval_query,
)


# Main router — prefix + JWT dependency applied here once.
router = APIRouter(
    prefix="/internal/v1",
    dependencies=[Depends(require_user)],
)

# Order: domain-organized; FastAPI matches by path so ordering is cosmetic
# unless two sub-routers register the same path (none do here).
router.include_router(_system_router)
router.include_router(_identity_router)
router.include_router(_data_sources_router)
router.include_router(_ingest_router)
router.include_router(_jobs_router)
router.include_router(_assets_router)
router.include_router(_ai_prompts_router)
router.include_router(_ai_governance_router)
router.include_router(_governance_router)
router.include_router(_governance_prompts_router)
router.include_router(_normalized_refs_router)
router.include_router(_record_assets_router)
router.include_router(_major_profiles_router)
router.include_router(_capability_graph_staging_router)
router.include_router(_evidence_graph_router)
router.include_router(_task_outline_router)
router.include_router(_knowledge_retrieval_router)


__all__ = ["router", "auth_router"]
