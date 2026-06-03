"use client";

import { Card, Skeleton } from "antd";

export default function Loading() {
  return (
    <div className="grid gap-4">
      <Card>
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
      <Card>
        <Skeleton active paragraph={{ rows: 5 }} />
      </Card>
      <Card>
        <Skeleton active paragraph={{ rows: 4 }} />
      </Card>
    </div>
  );
}
