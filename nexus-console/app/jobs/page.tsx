import { StatusLabel } from "@/components/StatusLabel";
import { jobStages, week2Demo } from "@/lib/week2-demo";

export default function JobsPage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-05</p>
          <h1>作业中心</h1>
          <p>展示接入后处理作业、阶段进度、失败原因和关联对象。</p>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>作业ID</span>
          <span>类型</span>
          <span>关联对象</span>
          <span>当前阶段</span>
          <span>状态</span>
          <span>创建时间</span>
        </div>
        <div className="table-row">
          <span>{week2Demo.jobId}</span>
          <span>ingest_process</span>
          <span>{week2Demo.rawObjectId}</span>
          <span>completed</span>
          <StatusLabel value="succeeded" />
          <span>{week2Demo.createdAt}</span>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>阶段</span>
          <span>阶段名</span>
          <span>输入对象</span>
          <span>输出对象</span>
          <span>状态</span>
        </div>
        {jobStages.map((stage) => (
          <div className="table-row" key={stage.label}>
            <span>{stage.label}</span>
            <span>{stage.values[0]}</span>
            <span>{stage.values[1]}</span>
            <span>{stage.values[2]}</span>
            {stage.status ? <StatusLabel value={stage.status} /> : <span />}
          </div>
        ))}
      </div>
    </section>
  );
}
