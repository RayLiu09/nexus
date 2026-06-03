"use client";

import Link from "next/link";
import { List } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import type { AIGovernanceRun } from "@/lib/api";

export function DecisionList({ items }: { items: AIGovernanceRun[] }) {
  if (items.length === 0) {
    return <div className="text-text-muted text-sm text-center py-4">待复核队列已清空</div>;
  }

  return (
    <List
      size="small"
      split={false}
      dataSource={items}
      renderItem={(gr) => (
        <Link
          href="/governance"
          key={gr.id}
          className="flex justify-between items-center py-2 px-3 rounded border border-line-light text-xs text-text no-underline mb-2 last:mb-0"
        >
          <code>{gr.normalized_ref_id.slice(0, 20)}&hellip;</code>
          <StatusLabel value={gr.adoption_status} />
        </Link>
      )}
    />
  );
}
