"use client";

import { Button, Card, Input, Segmented, Select, Space, Tag, Tooltip } from "antd";
import { PlayCircle, Search, Send } from "lucide-react";
import { useMemo, useState } from "react";

import type { FixturePreset } from "./fixtures.types";

export type QueryMode = "plan" | "full";

interface QueryFormProps {
  presets: FixturePreset[];
  submitting: boolean;
  onSubmit: (query: string, mode: QueryMode) => void;
}

const MIN_QUERY_LENGTH = 1;
const MAX_QUERY_LENGTH = 2000;

export function QueryForm({ presets, submitting, onSubmit }: QueryFormProps) {
  const [query, setQuery] = useState<string>("");
  const [mode, setMode] = useState<QueryMode>("plan");
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);

  const trimmed = query.trim();
  const canSubmit =
    !submitting &&
    trimmed.length >= MIN_QUERY_LENGTH &&
    trimmed.length <= MAX_QUERY_LENGTH;

  const presetOptions = useMemo(
    () =>
      presets.map((p) => ({
        value: p.id,
        label: p.label,
        preset: p,
      })),
    [presets],
  );

  const activePreset = selectedPresetId
    ? presets.find((p) => p.id === selectedPresetId)
    : null;

  const handlePresetChange = (id: string | null): void => {
    setSelectedPresetId(id);
    if (id) {
      const preset = presets.find((p) => p.id === id);
      if (preset) setQuery(preset.question);
    }
  };

  const handleSubmit = (): void => {
    if (!canSubmit) return;
    onSubmit(trimmed, mode);
  };

  return (
    <Card size="small" title="查询">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-gray-600">预设 case</span>
          <Select<string | null>
            value={selectedPresetId}
            options={presetOptions}
            onChange={handlePresetChange}
            allowClear
            placeholder="选择一个 M-C golden case 快速填充"
            style={{ minWidth: 320 }}
            data-testid="fixture-select"
          />
          {activePreset && (
            <Space size={4}>
              <Tag color="geekblue">{activePreset.domain_focus}</Tag>
              <Tag color="blue">{activePreset.category}</Tag>
              {activePreset.notes && (
                <Tooltip title={activePreset.notes}>
                  <span className="cursor-help text-xs text-gray-500">
                    了解此 case
                  </span>
                </Tooltip>
              )}
            </Space>
          )}
        </div>

        <div>
          <span className="mb-1 block text-sm text-gray-600">query</span>
          <Input.TextArea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入自然语言查询，或从上方选择预设 case"
            maxLength={MAX_QUERY_LENGTH}
            showCount
            autoSize={{ minRows: 2, maxRows: 5 }}
            data-testid="query-input"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-gray-600">模式</span>
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as QueryMode)}
            options={[
              {
                label: (
                  <span className="inline-flex items-center gap-1">
                    <Search size={14} />
                    Plan Only
                  </span>
                ),
                value: "plan",
              },
              {
                label: (
                  <span className="inline-flex items-center gap-1">
                    <PlayCircle size={14} />
                    Full Run
                  </span>
                ),
                value: "full",
              },
            ]}
            data-testid="mode-switch"
          />
          <Tooltip
            title={
              mode === "plan"
                ? "只跑 intent + planner，不执行 executors，快速看意图与计划。"
                : "跑完整 orchestrator：intent → planner → executors → DAG → rerank → summary。"
            }
          >
            <span className="cursor-help text-xs text-gray-400">?</span>
          </Tooltip>
          <Button
            type="primary"
            icon={<Send size={14} />}
            onClick={handleSubmit}
            disabled={!canSubmit}
            loading={submitting}
            className="ml-auto"
            data-testid="submit-button"
          >
            提交
          </Button>
        </div>
      </div>
    </Card>
  );
}
