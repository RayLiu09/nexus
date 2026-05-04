import { StatusLabel } from "@/components/StatusLabel";
import { week2Demo } from "@/lib/week2-demo";

export default function IngestPage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-03</p>
          <h1>数据接入</h1>
          <p>提交文件或爬虫 JSON 包，生成接入批次、原始对象、处理作业和资产化结果。</p>
        </div>
        <button className="primary-button">提交批次</button>
      </div>

      <div className="m1-flow">
        {["ingest_batch", "raw_object", "job", "parse_artifact", "normalized_ref", "asset"].map(
          (step) => (
            <span key={step}>{step}</span>
          )
        )}
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>文件名</span>
          <span>批次号</span>
          <span>数据源</span>
          <span>内容类型</span>
          <span>状态</span>
          <span>后续对象</span>
        </div>
        <div className="table-row">
          <span>{week2Demo.title}.pdf</span>
          <span>{week2Demo.batchId}</span>
          <span>{week2Demo.source}</span>
          <span>application/pdf</span>
          <StatusLabel value="completed" />
          <span>{week2Demo.rawObjectId}</span>
        </div>
      </div>
    </section>
  );
}
