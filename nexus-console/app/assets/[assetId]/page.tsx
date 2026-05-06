import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
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
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-07</p>
          <h1>资产详情 {shortId(assetId)}</h1>
          <p>从资产版本追溯标准化引用、解析产物和原始对象，当前版本由读取模型派生。</p>
        </div>
        {asset ? <StatusLabel value={asset.status} /> : null}
      </div>

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <div className="detail-grid">
        <div>
          <span>资产标题</span>
          <strong>{asset?.title ?? "-"}</strong>
        </div>
        <div>
          <span>读取模型当前版本</span>
          <strong>{shortId(result.data?.current_version?.id)}</strong>
        </div>
        <div>
          <span>读取模型标准化引用</span>
          <strong>{shortId(result.data?.current_normalized_ref?.id)}</strong>
        </div>
        <div>
          <span>原始对象</span>
          <strong>{shortId(latestVersion?.raw_object_id)}</strong>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>区域</span>
          <span>对象ID</span>
          <span>URI</span>
          <span>状态</span>
        </div>
        {latestVersion ? (
          <div className="table-row">
            <span>版本</span>
            <span>{shortId(latestVersion.id)}</span>
            <span className="mono-cell">{latestVersion.source_checksum}</span>
            <StatusLabel value={latestVersion.version_status} />
          </div>
        ) : null}
        {relatedArtifact ? (
          <div className="table-row">
            <span>解析产物</span>
            <span>{shortId(relatedArtifact.id)}</span>
            <span className="mono-cell">{relatedArtifact.artifact_uri}</span>
            <StatusLabel value={relatedArtifact.status} />
          </div>
        ) : null}
        {latestRef ? (
          <div className="table-row">
            <span>标准化引用</span>
            <span>{shortId(latestRef.id)}</span>
            <span className="mono-cell">{latestRef.object_uri}</span>
            <StatusLabel value={latestRef.status} />
          </div>
        ) : null}
        {!latestVersion && !relatedArtifact && !latestRef ? (
          <div className="empty-state">
            <strong>暂无真实资产详情</strong>
          </div>
        ) : null}
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>版本</span>
          <span>版本号</span>
          <span>原始对象</span>
          <span>更新时间</span>
          <span>状态</span>
        </div>
        {result.data?.versions.length ? (
          result.data.versions.map((version) => (
            <div className="table-row" key={version.id}>
              <span>{shortId(version.id)}</span>
              <span>v{version.version_no}</span>
              <span>{shortId(version.raw_object_id)}</span>
              <span>{formatDateTime(version.updated_at)}</span>
              <StatusLabel value={version.version_status} />
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无版本记录</strong>
          </div>
        )}
      </div>
    </section>
  );
}
