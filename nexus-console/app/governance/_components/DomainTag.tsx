"use client";

import { Tag } from "antd";

export function DomainTag({ classification }: { classification: string }) {
  return <Tag color="purple">{classification}</Tag>;
}
