"use client";

import { Drawer, Descriptions, Tag, Alert, Progress, Button } from "antd";
import { type GovernanceRun, getClassification, getLevel, getConfidence, getQualityScore, getQualityLevel, getTags, getOrgScope } from "../_lib/types";
import { ConfidenceTag } from "./ConfidenceTag";
import { DomainTag } from "./DomainTag";
import { LevelTag } from "./LevelTag";
import { AdoptionTag } from "./AdoptionTag";

interface DetailDrawerProps {
  run: GovernanceRun | null;
  open: boolean;
  onClose: () => void;
  onOpenTrail: (refId: string) => void;
}

export function DetailDrawer({ run, open, onClose, onOpenTrail }: DetailDrawerProps) {
  if (!run) return null;

  const aiOutput = run.ai_output ?? {};
  const qualitySummary = run.quality_summary ?? {};
  const dimScores = (qualitySummary.dimension_scores as Record<string, number>) ?? {};
  const blockingReasons = Array.isArray(qualitySummary.blocking_reasons)
    ? (qualitySummary.blocking_reasons as string[])
    : [];

  return (
    <Drawer
      title="决策追踪"
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={
        <div className="flex gap-2.5 justify-end">
          <Button onClick={onClose}>关闭</Button>
          <Button type="primary" onClick={() => onOpenTrail(run.normalized_ref_id)}>
            查看决策追踪
          </Button>
        </div>
      }
    >
      <Descriptions column={2} size="small" bordered className="mb-4">
        <Descriptions.Item label="模型别名">
          <code className="font-mono">{run.model_alias}</code>
        </Descriptions.Item>
        <Descriptions.Item label="Prompt 版本">{run.prompt_version}</Descriptions.Item>
        <Descriptions.Item label="验证状态">
          <Tag>{run.validation_status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="采纳状态">
          <AdoptionTag status={run.adoption_status} />
        </Descriptions.Item>
      </Descriptions>

      <h4 className="text-detail font-semibold mb-2">AI 建议</h4>
      <Descriptions column={2} size="small" className="mb-4">
        <Descriptions.Item label="分类">
          <DomainTag classification={getClassification(run)} />
        </Descriptions.Item>
        <Descriptions.Item label="分级">
          <LevelTag level={getLevel(run)} />
        </Descriptions.Item>
        <Descriptions.Item label="置信度">
          <ConfidenceTag confidence={getConfidence(run)} />
        </Descriptions.Item>
        <Descriptions.Item label="组织范围">{getOrgScope(run)}</Descriptions.Item>
        <Descriptions.Item label="标签" span={2}>
          {getTags(run).length > 0 ? (
            getTags(run).map((t) => <Tag key={t}>#{t}</Tag>)
          ) : (
            <span className="text-muted">-</span>
          )}
        </Descriptions.Item>
      </Descriptions>

      {(aiOutput.reasoning as string) && (
        <Alert
          type="info"
          message="AI 推理"
          description={aiOutput.reasoning as string}
          className="mb-4"
        />
      )}

      {run.quality_summary && (
        <>
          <h4 className="text-detail font-semibold mb-2">质量评分</h4>
          <Descriptions column={2} size="small" className="mb-3">
            <Descriptions.Item label="综合分">{getQualityScore(run) ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="质量等级">
              <Tag color={getQualityLevel(run) === "pass" ? "success" : "warning"}>
                {getQualityLevel(run) || "-"}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
          {Object.keys(dimScores).length > 0 && (
            <div className="grid gap-1.5 mb-4">
              {Object.entries(dimScores).map(([dim, score]) => (
                <div key={dim} className="flex items-center gap-2">
                  <span className="w-16 text-xs text-muted shrink-0">{dim}</span>
                  <Progress
                    percent={score}
                    size="small"
                    status={score >= 80 ? "success" : score >= 60 ? "normal" : "exception"}
                    className="flex-1"
                  />
                </div>
              ))}
            </div>
          )}
          {blockingReasons.length > 0 && (
            <Alert
              type="error"
              message="阻断原因"
              description={blockingReasons.map((reason, i) => (
                <div key={i}>{reason}</div>
              ))}
              className="mb-4"
            />
          )}
        </>
      )}

      {run.validation_error && (
        <Alert type="error" title="验证错误" description={run.validation_error} />
      )}
    </Drawer>
  );
}
