"use client";

import { Card, Skeleton } from "antd";

export default function Loading() {
  return (
    <div className="grid gap-4">
      <Card>
        <Skeleton active paragraph={{ rows: 1 }} />
      </Card>
      <Card>
        <Skeleton active paragraph={{ rows: 8 }} />
      </Card>
    </div>
  );
}
