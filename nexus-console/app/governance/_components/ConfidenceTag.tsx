"use client";

import { Tag } from "antd";
import { CheckOutlined, WarningOutlined, CloseOutlined } from "@ant-design/icons";

export function ConfidenceTag({ confidence }: { confidence: number }) {
  if (confidence >= 0.85)
    return (
      <Tag color="success" icon={<CheckOutlined />}>
        {(confidence * 100).toFixed(0)}%
      </Tag>
    );
  if (confidence >= 0.6)
    return (
      <Tag color="warning" icon={<WarningOutlined />}>
        {(confidence * 100).toFixed(0)}%
      </Tag>
    );
  return (
    <Tag color="error" icon={<CloseOutlined />}>
      {(confidence * 100).toFixed(0)}%
    </Tag>
  );
}
