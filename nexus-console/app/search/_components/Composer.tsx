"use client";

import {
  Button,
  Input,
  InputNumber,
  Segmented,
  Select,
  Slider,
  Space,
  Tooltip,
  Typography,
} from "antd";
import { FileSearch, Loader2, MessagesSquare, Search, Send } from "lucide-react";
import { useMemo } from "react";

import type { KnowledgeTypeOption } from "../_lib/searchTypes";
import type { Mode } from "../_lib/playgroundTypes";
import { DEFAULT_TOP_K } from "../_lib/playgroundTypes";

interface ComposerProps {
  mode: Mode;
  query: string;
  loading: boolean;
  onModeChange: (mode: Mode) => void;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
  kb: string | undefined;
  topK: number;
  threshold: number;
  knowledgeTypes: KnowledgeTypeOption[];
  onKbChange: (value: string | undefined) => void;
  onTopKChange: (value: number) => void;
  onThresholdChange: (value: number) => void;
}

export function Composer(props: ComposerProps) {
  const {
    mode,
    query,
    loading,
    onModeChange,
    onQueryChange,
    onSubmit,
    kb,
    topK,
    threshold,
    knowledgeTypes,
    onKbChange,
    onTopKChange,
    onThresholdChange,
  } = props;

  const modeOptions = useMemo(
    () => [
      {
        label: (
          <span className="inline-flex items-center gap-1.5">
            <MessagesSquare size={14} aria-hidden="true" />
            智能召回
          </span>
        ),
        value: "retrieval" as const,
      },
      {
        label: (
          <span className="inline-flex items-center gap-1.5">
            <Search size={14} aria-hidden="true" />
            语义检索
          </span>
        ),
        value: "search" as const,
      },
      {
        label: (
          <span className="inline-flex items-center gap-1.5">
            <FileSearch size={14} aria-hidden="true" />
            问答验证
          </span>
        ),
        value: "qa" as const,
      },
    ],
    [],
  );

  return (
    <div className="border-t border-[var(--line)] bg-[var(--surface)] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented<Mode>
          value={mode}
          onChange={onModeChange}
          options={modeOptions}
          disabled={loading}
        />
        {mode !== "retrieval" && (
          <>
            <Select
              allowClear
              className="min-w-64"
              placeholder="默认 textbook_kb"
              value={kb}
              onChange={(v) => onKbChange(v ?? undefined)}
              disabled={loading}
              options={knowledgeTypes.map((kt) => ({
                value: kt.code,
                label: `${kt.name}（${kt.code}）`,
              }))}
            />
            <Space.Compact>
              <div className="flex h-8 items-center rounded-s-md border border-e-0 border-[var(--line)] bg-[var(--surface-alt)] px-3 text-sm text-[var(--muted)]">
                top_k
              </div>
              <InputNumber
                min={1}
                max={50}
                value={topK}
                disabled={loading}
                onChange={(v) => onTopKChange(typeof v === "number" ? v : DEFAULT_TOP_K)}
              />
            </Space.Compact>
          </>
        )}
        {mode === "search" && (
          <div className="flex min-w-64 items-center gap-2">
            <Typography.Text type="secondary">阈值</Typography.Text>
            <Slider
              className="min-w-40"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              disabled={loading}
              onChange={onThresholdChange}
            />
            <Typography.Text className="w-10">{threshold.toFixed(2)}</Typography.Text>
          </div>
        )}
      </div>

      <div className="flex items-end gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 4 }}
          variant="borderless"
          value={query}
          disabled={loading}
          placeholder={
            mode === "retrieval"
              ? "输入需要检索/召回的问题"
              : mode === "search"
                ? "输入检索关键词"
                : "输入需要验证的问题"
          }
          onChange={(e) => onQueryChange(e.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault();
              void onSubmit();
            }
          }}
        />
        <Tooltip title={loading ? "当前任务执行中" : "发送"}>
          <Button
            type="primary"
            shape="circle"
            icon={loading ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
            disabled={loading || !query.trim()}
            onClick={() => void onSubmit()}
          />
        </Tooltip>
      </div>
    </div>
  );
}
