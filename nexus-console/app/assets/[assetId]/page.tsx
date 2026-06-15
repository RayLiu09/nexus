import Link from "next/link";
import { Button } from "antd";
import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { AssetDetailTabs } from "@/components/AssetDetailTabs";
import {
  getApiData,
  shortId,
  type AssetDetail,
  type ParseArtifact,
  type AIGovernanceRun,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AssetDetailPage({
  params,
}: {
  params: Promise<{ assetId: string }>;
}) {
  const { assetId } = await params;

  const [result, parseArtifacts] = await Promise.all([
    getApiData<AssetDetail | null>(`/internal/v1/assets/${assetId}`, null),
    getApiData<ParseArtifact[]>("/internal/v1/parse-artifacts", []),
  ]);

  const asset = result.data?.asset;
  const latestVersion = result.data?.current_version ?? result.data?.versions[0] ?? null;
  const latestRef = result.data?.current_normalized_ref ?? result.data?.normalized_refs[0] ?? null;
  const relatedArtifact =
    parseArtifacts.data.find((a) => a.asset_version_id === latestVersion?.id) ??
    parseArtifacts.data.find((a) => a.raw_object_id === latestVersion?.raw_object_id);

  // Fetch AI governance runs for the latest normalized ref
  const governanceRuns = latestRef
    ? await getApiData<AIGovernanceRun[]>(
        `/internal/v1/ai/governance-runs?normalized_ref_id=${latestRef.id}`,
        [],
      )
    : { data: [], ok: true, error: null, traceId: null };

  return (
    <>
      <PageHeader
        eyebrow="资产目录 — 详情与血缘"
        title={`资产详情 · ${asset?.title ?? shortId(assetId)}`}
        description="从资产版本追溯标准化引用、解析产物和原始对象，查看完整血缘链路。"
        actions={
          <div className="flex gap-2">
            {asset && <StatusLabel value={asset.status} />}
            <Link href="/assets">
              <Button type="text">← 返回目录</Button>
            </Link>
          </div>
        }
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      {/* Overview grid */}
      <div className="detail-grid">
        <div>
          <span>资产标题</span>
          <strong>{asset?.title ?? "-"}</strong>
        </div>
        <div>
          <span>资产类型</span>
          <strong>{asset?.asset_kind ?? "-"}</strong>
        </div>
        <div>
          <span>当前版本</span>
          <strong className="mono-cell">{shortId(result.data?.current_version?.id)}</strong>
        </div>
        <div>
          <span>标准化引用</span>
          <strong className="mono-cell">{shortId(result.data?.current_normalized_ref?.id)}</strong>
        </div>
        <div>
          <span>原始对象</span>
          <strong className="mono-cell">{shortId(latestVersion?.raw_object_id)}</strong>
        </div>
        <div>
          <span>数据源</span>
          <strong className="mono-cell">{shortId(asset?.data_source_id)}</strong>
        </div>
      </div>

      {/* Tabs: 血缘 / AI治理 / 质量评分 / 版本历史 */}
      <AssetDetailTabs
        latestVersion={latestVersion}
        latestRef={latestRef}
        relatedArtifact={relatedArtifact ?? null}
        asset={asset ?? null}
        versions={result.data?.versions ?? []}
        governanceRuns={governanceRuns.data}
      />
    </>
  );
}
