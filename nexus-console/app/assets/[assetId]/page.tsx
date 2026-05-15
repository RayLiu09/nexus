import Link from "next/link";
import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { DomainTag } from "@/components/DomainTag";
import { EmptyState } from "@/components/EmptyState";
import {
  formatDateTime,
  getApiData,
  shortId,
  type AssetDetail,
  type ParseArtifact
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AssetDetailPage({
  params
}: {
  params: Promise<{ assetId: string }>;
}) {
  const { assetId } = await params;
  const result = await getApiData<AssetDetail | null>(`/v1/assets/${assetId}`, null);
  const parseArtifacts = await getApiData<ParseArtifact[]>("/v1/parse-artifacts", []);
  const asset = result.data?.asset;
  const latestVersion = result.data?.current_version ?? result.data?.versions[0] ?? null;
  const latestRef =
    result.data?.current_normalized_ref ?? result.data?.normalized_refs[0] ?? null;
  const relatedArtifact =
    parseArtifacts.data.find((artifact) => artifact.document_version_id === latestVersion?.id) ??
    parseArtifacts.data.find((artifact) => artifact.raw_object_id === latestVersion?.raw_object_id);

  return (
    <>
      <PageHeader
        prototypeId="NX-07"
        title={`资产详情 · ${asset?.title ?? shortId(assetId)}`}
        description="从资产版本追溯标准化引用、解析产物和原始对象，查看完整血缘链路。"
        actions={
          <div className="flex gap-2">
            {asset && <StatusLabel value={asset.status} />}
            <Link href="/assets" className="btn btn-ghost btn-sm">
              ← 返回目录
            </Link>
          </div>
        }
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      {/* Detail grid */}
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
          <span>当前版本（读取模型）</span>
          <strong className="mono-cell">{shortId(result.data?.current_version?.id)}</strong>
        </div>
        <div>
          <span>标准化引用（读取模型）</span>
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

      {/* Lineage DAG — simplified trace view */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">血缘追溯</span>
          <span className="text-xs text-muted">raw → parse → normalize → asset</span>
        </div>
        <div className="card-body">
          <div className="m1-flow">
            <span className={latestVersion ? "done" : ""}>
              Raw Object
              {latestVersion && (
                <span className="text-xs text-muted" style={{ display: "block" }}>
                  {shortId(latestVersion.raw_object_id)}
                </span>
              )}
            </span>
            <span className={relatedArtifact ? "done" : ""}>
              Parse Artifact
              {relatedArtifact && (
                <span className="text-xs text-muted" style={{ display: "block" }}>
                  {relatedArtifact.parse_mode}
                </span>
              )}
            </span>
            <span className={latestRef ? "done" : ""}>
              Normalized
              {latestRef && (
                <span className="text-xs text-muted" style={{ display: "block" }}>
                  {latestRef.normalized_type}
                </span>
              )}
            </span>
            <span className={asset?.status === "available" ? "done" : "active"}>
              Asset
              {asset && (
                <span className="text-xs text-muted" style={{ display: "block" }}>
                  {asset.status}
                </span>
              )}
            </span>
          </div>
        </div>
      </div>

      {/* Lineage detail table */}
      <div className="table-frame">
        <div className="table-head">
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span>层级</span>
            <span>对象ID</span>
            <span>URI / 校验</span>
            <span>状态</span>
          </div>
        </div>
        {latestVersion ? (
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span className="font-bold">版本</span>
            <span className="mono-cell">{shortId(latestVersion.id)}</span>
            <span className="mono-cell">{latestVersion.source_checksum}</span>
            <StatusLabel value={latestVersion.version_status} />
          </div>
        ) : null}
        {relatedArtifact ? (
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span className="font-bold">解析产物</span>
            <span className="mono-cell">{shortId(relatedArtifact.id)}</span>
            <span className="mono-cell">{relatedArtifact.artifact_uri}</span>
            <StatusLabel value={relatedArtifact.status} />
          </div>
        ) : null}
        {latestRef ? (
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span className="font-bold">标准化引用</span>
            <span className="mono-cell">{shortId(latestRef.id)}</span>
            <span className="mono-cell">{latestRef.object_uri}</span>
            <StatusLabel value={latestRef.status} />
          </div>
        ) : null}
        {!latestVersion && !relatedArtifact && !latestRef ? (
          <EmptyState icon="🔗" title="暂无血缘数据" description="继续完成接入和标准化流水线以生成完整血缘链路" />
        ) : null}
      </div>

      {/* Version history */}
      <div className="table-frame">
        <div className="table-head">
          <div className="table-row" style={{ gridTemplateColumns: "140px 60px 140px 140px 100px" }}>
            <span>版本ID</span>
            <span>版本号</span>
            <span>原始对象</span>
            <span>更新时间</span>
            <span>状态</span>
          </div>
        </div>
        {result.data?.versions.length ? (
          result.data.versions.map((version) => (
            <div className="table-row" key={version.id} style={{ gridTemplateColumns: "140px 60px 140px 140px 100px" }}>
              <span className="mono-cell">{shortId(version.id)}</span>
              <span>v{version.version_no}</span>
              <span className="mono-cell">{shortId(version.raw_object_id)}</span>
              <span className="text-sm text-muted">{formatDateTime(version.updated_at)}</span>
              <StatusLabel value={version.version_status} />
            </div>
          ))
        ) : (
          <EmptyState icon="📋" title="暂无版本记录" />
        )}
      </div>
    </>
  );
}
