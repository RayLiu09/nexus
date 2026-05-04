import { StatusLabel } from "@/components/StatusLabel";
import { week2Demo } from "@/lib/week2-demo";

export default function AssetDetailPage({ params }: { params: { assetId: string } }) {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-07</p>
          <h1>资产详情 {params.assetId}</h1>
          <p>从资产版本追溯标准化引用、解析产物和原始对象，当前版本由读取模型派生。</p>
        </div>
        <StatusLabel value="available" />
      </div>

      <div className="detail-grid">
        <div>
          <span>资产标题</span>
          <strong>{week2Demo.title}</strong>
        </div>
        <div>
          <span>当前版本</span>
          <strong>{week2Demo.versionId}</strong>
        </div>
        <div>
          <span>标准化引用</span>
          <strong>{week2Demo.normalizedRefId}</strong>
        </div>
        <div>
          <span>原始对象</span>
          <strong>{week2Demo.rawObjectId}</strong>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>区域</span>
          <span>对象ID</span>
          <span>URI</span>
          <span>状态</span>
        </div>
        <div className="table-row">
          <span>版本</span>
          <span>{week2Demo.versionId}</span>
          <span className="mono-cell">{week2Demo.objectUri}</span>
          <StatusLabel value="available" />
        </div>
        <div className="table-row">
          <span>解析产物</span>
          <span>{week2Demo.parseArtifactId}</span>
          <span className="mono-cell">{week2Demo.artifactUri}</span>
          <StatusLabel value="succeeded" />
        </div>
        <div className="table-row">
          <span>标准化引用</span>
          <span>{week2Demo.normalizedRefId}</span>
          <span className="mono-cell">{week2Demo.normalizedUri}</span>
          <StatusLabel value="available" />
        </div>
      </div>
    </section>
  );
}
