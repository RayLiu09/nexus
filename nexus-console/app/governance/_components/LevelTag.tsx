"use client";

import { Tag } from "antd";

const LEVEL_MAP: Record<string, string> = {
  L1: "success",
  L2: "processing",
  L3: "warning",
  L4: "error",
};

export function LevelTag({ level }: { level: string }) {
  return <Tag color={LEVEL_MAP[level] ?? "default"}>{level}</Tag>;
}
