"use client";

import Link from "next/link";
import { List, Tooltip } from "antd";
import { CheckCircleOutlined } from "@ant-design/icons";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { shortId, type AIGovernanceRun } from "@/lib/api";

export function DecisionList({ items }: { items: AIGovernanceRun[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        size="small"
        icon={<CheckCircleOutlined />}
        title="队列已清空"
        hint="暂无需要人工复核的治理结果"
        actions={[
          { label: "前往治理中心", href: "/governance", type: "default" },
          { label: "配置自动采纳规则", href: "/rules", type: "text" },
        ]}
      />
    );
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
          className="border-line-light text-text hover:bg-bg-alt mb-2 flex items-center justify-between rounded border px-3 py-2 text-xs no-underline last:mb-0"
        >
          <Tooltip title={gr.normalized_ref_id}>
            <code className="font-mono">{shortId(gr.normalized_ref_id)}</code>
          </Tooltip>
          <StatusLabel value={gr.adoption_status} />
        </Link>
      )}
    />
  );
}
