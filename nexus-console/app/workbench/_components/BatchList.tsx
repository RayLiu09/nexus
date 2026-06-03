"use client";

import { List } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import type { IngestBatch } from "@/lib/api";

export function BatchList({ batches }: { batches: IngestBatch[] }) {
  if (batches.length === 0) {
    return <div className="text-text-muted text-sm text-center py-4">暂无批次</div>;
  }

  return (
    <List
      size="small"
      split={false}
      dataSource={batches}
      renderItem={(b) => {
        const { display, iso } = formatTime(b.created_at);
        return (
          <div key={b.id} className="flex justify-between items-center text-xs">
            <span className="font-mono">{b.id.slice(0, 12)}&hellip;</span>
            <StatusLabel value={b.status} />
            <time dateTime={iso} title={iso} className="text-text-muted">
              {display}
            </time>
          </div>
        );
      }}
    />
  );
}
