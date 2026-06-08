"use client";

import { Card, Skeleton } from "antd";

export default function Loading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <Card className="w-full max-w-[400px]">
        <Skeleton active paragraph={{ rows: 3 }} />
      </Card>
    </div>
  );
}
