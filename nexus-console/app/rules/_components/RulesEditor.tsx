"use client";

import { useMemo } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Radio,
  Space,
  Tag,
  Typography,
} from "antd";
import { FormatPainterOutlined } from "@ant-design/icons";
import type { CheckboxChangeEvent } from "antd/es/checkbox";
import type { RecomputeScope } from "@/lib/governance-rules-api";

interface RulesEditorProps {
  editorText: string;
  onChange: (val: string) => void;
  editorError: string | null;
  recompute: boolean;
  recomputeScope: RecomputeScope;
  onRecomputeChange: (e: CheckboxChangeEvent) => void;
  onScopeChange: (v: RecomputeScope) => void;
}

export function RulesEditor({
  editorText,
  onChange,
  editorError,
  recompute,
  recomputeScope,
  onRecomputeChange,
  onScopeChange,
}: RulesEditorProps) {
  const jsonValid = useMemo(() => {
    try {
      JSON.parse(editorText);
      return true;
    } catch {
      return false;
    }
  }, [editorText]);

  const lineCount = useMemo(
    () => editorText.split("\n").length,
    [editorText],
  );

  function handleFormat() {
    try {
      const parsed = JSON.parse(editorText);
      onChange(JSON.stringify(parsed, null, 2));
    } catch {
      // Silently ignore — format only works on valid JSON
    }
  }

  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <Card
        title={
          <Space>
            <span>编辑 governance_rules.json</span>
            <Tag color="warning">编辑中</Tag>
            <Tag color={jsonValid ? "success" : "error"}>
              {jsonValid ? "JSON 有效" : "JSON 无效"}
            </Tag>
          </Space>
        }
        extra={
          <Space>
            <span className="text-xs text-muted">{lineCount} 行</span>
            <Button
              size="small"
              icon={<FormatPainterOutlined />}
              onClick={handleFormat}
              disabled={!jsonValid}
            >
              格式化
            </Button>
          </Space>
        }
        styles={{ body: { padding: 0 } }}
      >
        <textarea
          value={editorText}
          onChange={(e) => onChange(e.target.value)}
          className="block w-full min-h-[480px] resize-y border-none p-4 font-mono text-detail leading-relaxed outline-none rounded-b-lg bg-[var(--gray-900)] text-[#e5e7eb]"
          spellCheck={false}
          aria-label="governance_rules.json 编辑器"
        />
        {editorError && (
          <Alert className="m-3" type="error" showIcon title={editorError} />
        )}
      </Card>

      <Card title="保存选项 — 批量重跑（Review §5.4）">
        <Space orientation="vertical" size="small">
          <Checkbox checked={recompute} onChange={onRecomputeChange}>
            保存后对受影响的数据触发批量重跑
          </Checkbox>
          <Typography.Paragraph type="secondary" className="!mb-0 text-xs">
            勾选后，本次规则变更命中的 normalized_ref 会按下方范围重新调度治理。AVAILABLE
            版本不会被自动改写（仅写入审计），避免破坏已发布索引。
          </Typography.Paragraph>
          <Radio.Group
            disabled={!recompute}
            value={recomputeScope}
            onChange={(e) => onScopeChange(e.target.value)}
            optionType="default"
          >
            <Space orientation="vertical">
              <Radio value="review_required_only">
                仅 <code>review_required</code> 版本回流到 processing（默认 / 较安全）
              </Radio>
              <Radio value="all_affected">
                包含 <code>available</code>：仍只把 review_required 版本回流，
                额外把 available 版本登记到审计日志，便于人工逐条决定是否重跑
              </Radio>
            </Space>
          </Radio.Group>
        </Space>
      </Card>
    </Space>
  );
}
