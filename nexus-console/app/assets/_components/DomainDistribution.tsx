"use client";

import { Card, Progress } from "antd";
import type { DomainDistItem } from "../_lib/types";

const DOMAIN_COLORS = [
  "var(--domain-d1)",
  "var(--domain-d2)",
  "var(--domain-d3)",
  "var(--domain-d4)",
  "var(--domain-d5)",
  "var(--domain-d6)",
  "var(--brand)",
  "var(--success)",
  "var(--warning)",
  "var(--info)",
  "var(--text-muted)",
];

function domainColor(domain: string): string {
  let hash = 0;
  for (const ch of domain) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return DOMAIN_COLORS[hash % DOMAIN_COLORS.length];
}

export function DomainDistribution({ items }: { items: DomainDistItem[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));

  return (
    <Card
      title="数据域分布"
      size="small"
      extra={<span style={{ fontSize: 12, color: "var(--text-muted)" }}>仅保留必要分布</span>}
    >
      <div className="domain-dist">
        {items.map((item) => (
          <div key={item.domain} className="domain-dist-row">
            <span className="domain-dist-label">
              <span className="domain-dist-code" style={{ color: domainColor(item.domain) }}>
                {item.label}
              </span>
            </span>
            <Progress
              percent={Math.round((item.count / max) * 100)}
              showInfo={false}
              strokeColor={domainColor(item.domain)}
              railColor="var(--line-light)"
              size="small"
            />
            <strong className="domain-dist-count">{item.count}</strong>
          </div>
        ))}
      </div>
    </Card>
  );
}
