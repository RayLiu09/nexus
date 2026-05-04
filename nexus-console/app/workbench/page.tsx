import { StatusLabel } from "@/components/StatusLabel";
import { week2Demo } from "@/lib/week2-demo";

export default function WorkbenchPage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-01</p>
          <h1>工作台</h1>
          <p>M1 接入到资产化链路总览，覆盖批次、原始对象、作业、标准化引用和资产。</p>
        </div>
      </div>

      <div className="detail-grid">
        <div>
          <span>接入批次</span>
          <strong>{week2Demo.batchId}</strong>
        </div>
        <div>
          <span>处理作业</span>
          <strong>{week2Demo.jobId}</strong>
        </div>
        <div>
          <span>资产</span>
          <strong>{week2Demo.assetId}</strong>
        </div>
        <div>
          <span>链路状态</span>
          <StatusLabel value="completed" />
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>批次号</span>
          <span>来源</span>
          <span>原始对象</span>
          <span>作业</span>
          <span>标准化引用</span>
          <span>状态</span>
        </div>
        <div className="table-row">
          <span>{week2Demo.batchId}</span>
          <span>{week2Demo.source}</span>
          <span>{week2Demo.rawObjectId}</span>
          <span>{week2Demo.jobId}</span>
          <span>{week2Demo.normalizedRefId}</span>
          <StatusLabel value="completed" />
        </div>
      </div>
    </section>
  );
}
