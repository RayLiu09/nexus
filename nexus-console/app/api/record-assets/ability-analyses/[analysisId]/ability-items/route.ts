import { pickSearchParams, proxyInternalList } from "../../../_proxy";
import type { OccupationalAbilityItem } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ analysisId: string }> },
): Promise<Response> {
  const { analysisId } = await context.params;
  if (!analysisId) {
    return Response.json(
      { error: { message: "analysis_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const search = pickSearchParams(request, [
    { from: "category" },
    { from: "task_code" },
    { from: "work_content_code" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<OccupationalAbilityItem>(
    `/internal/v1/record-assets/ability-analyses/${encodeURIComponent(analysisId)}/ability-items`,
    search,
  );
}
