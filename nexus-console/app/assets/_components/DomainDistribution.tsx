"use client";

import { Card, Progress } from "antd";
import type { DomainDistItem } from "../_lib/types";

const DOMAIN_COLOR: Record<string, string> = {
  D1: "var(--domain-d1)",
  D2: "var(--domain-d2)",
  D3: "var(--domain-d3)",
  D4: "var(--domain-d4)",
  D5: "var(--domain-d5)",
  D6: "var(--domain-d6)",
};

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
              <span className="domain-dist-code" style={{ color: DOMAIN_COLOR[item.domain] }}>
                {item.domain}
              </span>
              <span className="domain-dist-name">{item.label}</span>
            </span>
            <Progress
              percent={Math.round((item.count / max) * 100)}
              showInfo={false}
              strokeColor={DOMAIN_COLOR[item.domain]}
              trailColor="var(--line-light)"
              size="small"
            />
            <strong className="domain-dist-count">{item.count}</strong>
          </div>
        ))}
      </div>
    </Card>
  );
}
