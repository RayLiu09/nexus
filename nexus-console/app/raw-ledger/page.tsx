import { StatusLabel } from "@/components/StatusLabel";
import { week2Demo } from "@/lib/week2-demo";

export default function RawLedgerPage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-04</p>
          <h1>原始数据台账</h1>
          <p>按批次和对象追溯原始留存位置、checksum、来源和接入状态。</p>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>原始对象</span>
          <span>批次号</span>
          <span>对象 URI</span>
          <span>Checksum</span>
          <span>状态</span>
        </div>
        <div className="table-row">
          <span>{week2Demo.rawObjectId}</span>
          <span>{week2Demo.batchId}</span>
          <span className="mono-cell">{week2Demo.objectUri}</span>
          <span>{week2Demo.checksum}</span>
          <StatusLabel value="raw_persisted" />
        </div>
      </div>
    </section>
  );
}
