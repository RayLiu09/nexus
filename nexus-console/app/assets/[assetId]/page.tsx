import Link from "next/link";
import { Button } from "antd";
import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { CopyableShortId } from "@/components/shared/CopyableShortId";
import { AssetDetailTabs } from "@/components/AssetDetailTabs";
import {
  getApiData,
  shortId,
  type AssetDetail,
  type ParseArtifact,
  type AIGovernanceRun,
  type DataSource,
  type RawObject,
  type TaskOutlineEnvelope,
} from "@/lib/api";
import { buildTagDictionary, type TagDictionaryEntry } from "@/lib/tagLabels";

export const dynamic = "force-dynamic";

function extractFilename(obj: RawObject): string {
  const metaName = obj.metadata_summary?.filename;
  if (typeof metaName === "string" && metaName.length > 0) return metaName;
  const uri = obj.source_uri || obj.object_uri;
  if (uri) {
    const last = uri.split("/").pop();
    if (last && last.length > 0) return last;
  }
  return "-";
}

export default async function AssetDetailPage({
  params,
}: {
  params: Promise<{ assetId: string }>;
}) {
  const { assetId } = await params;

  const [result, parseArtifacts, rulesResult] = await Promise.all([
    getApiData<AssetDetail | null>(`/internal/v1/assets/${assetId}`, null),
    getApiData<ParseArtifact[]>("/internal/v1/parse-artifacts", []),
    getApiData<{ tags?: TagDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  const tagDictionary = buildTagDictionary(rulesResult.data.tags);

  const asset = result.data?.asset;
  const versions = result.data?.versions ?? [];
  const displayVersion = result.data?.current_version ?? result.data?.latest_version ?? versions[0] ?? null;
  const displayRef = result.data?.current_normalized_ref ?? result.data?.latest_normalized_ref ?? result.data?.normalized_refs[0] ?? null;
  const relatedArtifact =
    parseArtifacts.data.find((a) => a.asset_version_id === displayVersion?.id) ??
    parseArtifacts.data.find((a) => a.raw_object_id === displayVersion?.raw_object_id);

  // Fetch data source and raw object names in parallel
  const [dataSourceResult, rawObjectNames] = await (async () => {
    const dsId = asset?.data_source_id;
    const rawIds = [...new Set(versions.map((v) => v.raw_object_id).filter(Boolean))] as string[];

    const [ds, ...rawResults] = await Promise.all([
      dsId ? getApiData<DataSource>(`/internal/v1/data-sources/${dsId}`, null as unknown as DataSource) : null,
      ...rawIds.map((id) => getApiData<RawObject>(`/internal/v1/raw-objects/${id}`, null as unknown as RawObject)),
    ]);

    const nameMap = new Map<string, string>();
    for (const r of rawResults) {
      if (r?.ok && r.data) nameMap.set(r.data.id, extractFilename(r.data));
    }

    return [ds, nameMap] as const;
  })();

  const dataSourceName = dataSourceResult?.ok ? dataSourceResult.data?.name ?? dataSourceResult.data?.code ?? null : null;

  // Fetch AI governance runs for the latest normalized ref
  const governanceRuns = displayRef
    ? await getApiData<AIGovernanceRun[]>(
        `/internal/v1/ai/governance-runs?normalized_ref_id=${displayRef.id}`,
        [],
      )
    : { data: [], ok: true, error: null, traceId: null, total: null };
  const taskOutline =
    displayRef?.normalized_type === "document"
      ? await getApiData<TaskOutlineEnvelope | null>(
          `/internal/v1/normalized-refs/${displayRef.id}/task-outline`,
          null,
        )
      : { data: null, ok: true, error: null, traceId: null, total: null };

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
          <CopyableShortId value={displayVersion?.id} className="mono-cell" />
        </div>
        <div>
          <span>标准化引用</span>
          <CopyableShortId value={displayRef?.id} className="mono-cell" />
        </div>
        <div>
          <span>原始对象</span>
          {displayVersion?.raw_object_id ? (
            rawObjectNames.has(displayVersion.raw_object_id) ? (
              <strong title={displayVersion.raw_object_id}>{rawObjectNames.get(displayVersion.raw_object_id)}</strong>
            ) : (
              <CopyableShortId value={displayVersion.raw_object_id} className="mono-cell" />
            )
          ) : (
            <strong>-</strong>
          )}
        </div>
        <div>
          <span>数据源</span>
          {dataSourceName ? (
            <strong title={asset?.data_source_id}>{dataSourceName}</strong>
          ) : asset?.data_source_id ? (
            <CopyableShortId value={asset.data_source_id} className="mono-cell" />
          ) : (
            <strong>-</strong>
          )}
        </div>
      </div>

      {/* Tabs: 血缘 / AI治理 / 质量评分 / 版本历史 */}
      <AssetDetailTabs
        latestVersion={displayVersion}
        latestRef={displayRef}
        relatedArtifact={relatedArtifact ?? null}
        asset={asset ?? null}
        versions={versions}
        governanceRuns={governanceRuns.data}
        latestGovernanceResult={result.data?.latest_governance_result ?? null}
        governanceRunsOk={governanceRuns.ok}
        governanceRunsError={governanceRuns.error}
        governanceRunsTraceId={governanceRuns.traceId}
        taskOutline={taskOutline.data}
        taskOutlineOk={taskOutline.ok}
        taskOutlineError={taskOutline.error}
        taskOutlineTraceId={taskOutline.traceId}
        rawObjectNames={rawObjectNames}
        dataSourceName={dataSourceName}
        tagDictionary={tagDictionary}
      />
    </>
  );
}
