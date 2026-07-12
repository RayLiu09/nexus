"use client";

import { Card, Empty, Tag } from "antd";
import { BookOpen } from "lucide-react";

import type {
  FriendlyOverallSummary,
  FriendlyRetrievalPlanView,
} from "@/lib/retrievalTypes";

import { FriendlyIntentSummary } from "./FriendlyIntentSummary";
import { FriendlySubQueryCard } from "./FriendlySubQueryCard";

interface FriendlyPlanViewProps {
  friendlyView: FriendlyRetrievalPlanView | null | undefined;
}

/**
 * v1.3 §5.5 planner-emitted natural-language projection. When the
 * backend orchestrator populates `retrieval_plan.friendly_view`, we
 * render it verbatim: intent summary → per-sub_query cards →
 * overall summary. Chinese labels come from
 * `nexus_app.retrieval.display_labels` — no client-side derivation.
 *
 * Skipped (Empty) when `friendlyView` is missing so upstream callers
 * can render the shared `PlanSection` (raw sub_queries JSON) as a
 * developer-friendly fallback.
 */
export function FriendlyPlanView({ friendlyView }: FriendlyPlanViewProps) {
  if (!friendlyView) {
    return (
      <Card
        size="small"
        title={
          <span className="inline-flex items-center gap-2">
            <BookOpen size={16} className="text-brand" />
            检索/召回思路（可读版）
          </span>
        }
        data-testid="friendly-plan-view-empty"
      >
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="本次响应未附带 friendly_view — planner 可能是 v1.2 或未启用"
        />
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title={
        <span className="inline-flex items-center gap-2">
          <BookOpen size={16} className="text-brand" />
          检索/召回思路（可读版）
        </span>
      }
      data-testid="friendly-plan-view"
    >
      <div className="flex flex-col gap-3">
        <FriendlyIntentSummary intent={friendlyView.intent_summary} />

        {friendlyView.sub_query_cards.length > 0 && (
          <div className="flex flex-col gap-3">
            {friendlyView.sub_query_cards.map((card) => (
              <FriendlySubQueryCard key={card.query_id} card={card} />
            ))}
          </div>
        )}

        <OverallFooter overall={friendlyView.overall} />
      </div>
    </Card>
  );
}

function OverallFooter({ overall }: { overall: FriendlyOverallSummary }) {
  const estimated =
    overall.estimated_duration_ms != null
      ? formatDuration(overall.estimated_duration_ms)
      : null;
  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-md bg-gray-50 p-3 text-xs text-gray-700"
      data-testid="friendly-overall-summary"
    >
      <span>
        共 <b>{overall.total_sub_queries}</b> 步
      </span>
      <span className="text-gray-400">·</span>
      <span>
        最大依赖深度 <b>{overall.max_depth}</b>
      </span>
      {estimated && (
        <>
          <span className="text-gray-400">·</span>
          <span>
            预计耗时 <b>{estimated}</b>
          </span>
        </>
      )}
      <Tag color="blue" className="ml-auto">
        {overall.combine_summary}
      </Tag>
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
