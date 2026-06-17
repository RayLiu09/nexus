"use client";

import { Typography } from "antd";
import { shortId } from "@/lib/api";

type Props = {
  value: string | null | undefined;
  className?: string;
  empty?: string;
};

export function CopyableShortId({ value, className, empty = "-" }: Props) {
  if (!value) return <span className={className}>{empty}</span>;

  return (
    <Typography.Text
      className={className ?? "font-mono text-xs"}
      title={value}
      copyable={{ text: value, tooltips: ["复制完整 ID", "已复制"] }}
    >
      {shortId(value)}
    </Typography.Text>
  );
}
