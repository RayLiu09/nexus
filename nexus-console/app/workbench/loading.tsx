"use client";

import { Card, Skeleton } from "antd";

export default function Loading() {
  return (
    <div className="grid gap-4">
      <Card>
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} size="small">
            <Skeleton active paragraph={{ rows: 1 }} />
          </Card>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <Skeleton active paragraph={{ rows: 8 }} />
        </Card>
        <Card>
          <Skeleton active paragraph={{ rows: 5 }} />
        </Card>
      </div>
    </div>
  );
}
