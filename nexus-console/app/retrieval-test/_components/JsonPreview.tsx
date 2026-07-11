"use client";

import { Button, message } from "antd";
import { Copy } from "lucide-react";
import { useMemo } from "react";

interface JsonPreviewProps {
  value: unknown;
  /** Max height in pixels; adds vertical scroll beyond it. */
  maxHeight?: number;
  /** Aria-label / hover title for the copy button. */
  label?: string;
}

export function JsonPreview({ value, maxHeight = 320, label = "JSON" }: JsonPreviewProps) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  return (
    <div className="relative">
      <Button
        size="small"
        icon={<Copy size={14} />}
        aria-label={`复制 ${label}`}
        className="absolute right-2 top-2 z-10"
        onClick={() => {
          void navigator.clipboard.writeText(text).then(
            () => message.success("已复制到剪贴板"),
            () => message.error("复制失败"),
          );
        }}
      >
        复制
      </Button>
      <pre
        className="m-0 overflow-auto rounded-md bg-gray-50 p-3 font-mono text-xs leading-relaxed text-gray-800"
        style={{ maxHeight }}
      >
        {text}
      </pre>
    </div>
  );
}
