import { StatusLabel } from "@/components/StatusLabel";
import type { StatusValue } from "@/lib/status";

type PageScaffoldProps = {
  title: string;
  prototypeId: string;
  summary: string;
  columns: string[];
  statuses?: StatusValue[];
  primaryAction?: string;
};

export function PageScaffold({
  title,
  prototypeId,
  summary,
  columns,
  statuses = ["processing", "available", "review_required", "failed"],
  primaryAction
}: PageScaffoldProps) {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">{prototypeId}</p>
          <h1>{title}</h1>
          <p>{summary}</p>
        </div>
        {primaryAction ? <button className="primary-button">{primaryAction}</button> : null}
      </div>

      <div className="toolbar">
        <div className="filter-slot">筛选</div>
        <div className="status-row">
          {statuses.map((status) => (
            <StatusLabel key={status} value={status} />
          ))}
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          {columns.map((column) => (
            <span key={column}>{column}</span>
          ))}
        </div>
        <div className="empty-state">
          <strong>暂无数据</strong>
        </div>
      </div>
    </section>
  );
}
