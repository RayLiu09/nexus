import { pickSearchParams, proxyInternalList } from "../../../_proxy";
import type { OccupationalWorkTask } from "@/lib/api";

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
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<OccupationalWorkTask>(
    `/internal/v1/record-assets/ability-analyses/${encodeURIComponent(analysisId)}/tasks`,
    search,
  );
}
