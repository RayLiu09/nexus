"use client";

import { Card, Empty, Tag, Tooltip } from "antd";
import { AlertTriangle, Info } from "lucide-react";

import {
  TONE_TO_TAG_COLOR,
  extractCode,
  lookupWarning,
} from "./warnings-catalog";

interface WarningsPanelProps {
  warnings: string[];
}

export function WarningsPanel({ warnings }: WarningsPanelProps) {
  return (
    <Card
      size="small"
      title={
        <span className="inline-flex items-center gap-2">
          <AlertTriangle size={16} className="text-warning" />
          告警与提示 ({warnings.length})
        </span>
      }
    >
      {warnings.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="本次执行未产生告警"
        />
      ) : (
        <ul className="flex list-none flex-col gap-2 p-0">
          {warnings.map((code, idx) => (
            <WarningItem key={`${code}-${idx}`} rawCode={code} />
          ))}
        </ul>
      )}
    </Card>
  );
}

interface WarningItemProps {
  rawCode: string;
}

function WarningItem({ rawCode }: WarningItemProps) {
  const meta = lookupWarning(rawCode);
  const headToken = extractCode(rawCode);
  // Show the raw code (including any `:...` detail) as a monospace suffix
  // so operators can grep logs when the label alone isn't specific enough.
  const detailSuffix = rawCode === headToken ? null : rawCode.slice(headToken.length);

  if (!meta) {
    // Unknown code — surface as info tone with the raw string so nothing
    // ever silently disappears from the UI.
    return (
      <li className="flex items-start gap-2">
        <Tag color={TONE_TO_TAG_COLOR.info} className="mt-0.5 font-mono">
          {rawCode}
        </Tag>
        <span className="text-xs text-gray-500">
          未在词典中登记的告警码（不影响执行）
        </span>
      </li>
    );
  }

  return (
    <li className="flex items-start gap-2">
      <Tag color={TONE_TO_TAG_COLOR[meta.tone]} className="mt-0.5">
        {meta.label}
      </Tag>
      {detailSuffix && (
        <span className="mt-1 font-mono text-xs text-gray-400">{detailSuffix}</span>
      )}
      <Tooltip title={`${headToken}: ${meta.description}`}>
        <Info size={14} className="mt-1 shrink-0 text-gray-400" />
      </Tooltip>
      <span className="text-xs text-gray-600">{meta.description}</span>
    </li>
  );
}
