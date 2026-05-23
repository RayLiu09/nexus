import { getApiData, type ApiResult } from "@/lib/api";
import type {
  DecisionTrailView,
  GovernanceResultRead,
} from "./decisionTrail.types";

/** 按 normalized_ref_id 拉取最新 GovernanceResult；view 控制脱敏视图。 */
export function fetchGovernanceResultForRef(
  refId: string,
  view: DecisionTrailView,
): Promise<ApiResult<GovernanceResultRead | null>> {
  // 注意：后端在没有 GovernanceResult 时返回 404，这里通过 fallback=null 兜底；
  // ApiResult.ok=false 即视为暂无 decision_trail。
  return getApiData<GovernanceResultRead | null>(
    `/v1/normalized-refs/${encodeURIComponent(refId)}/governance-result?view=${view}`,
    null,
  );
}
