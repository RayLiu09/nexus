"use client";

import { Card, Skeleton } from "antd";

export default function Loading() {
  return (
    <div className="grid gap-4">
      <Card>
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i} size="small">
            <Skeleton active paragraph={{ rows: 3 }} />
          </Card>
        ))}
      </div>
    </div>
  );
}
