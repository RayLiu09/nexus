"use client";

import { useEffect, useState } from "react";
import { Segmented } from "antd";

import { ChunkListSection } from "./ChunkListSection";
// Evidence Graph is temporarily hidden: block-level extraction is too fine
// and produces low-quality graphs. See knowledge outline P2/P3 plans for
// the replacement. Re-enable by flipping SHOW_EVIDENCE_GRAPH below.
// import { EvidenceGraphView } from "./EvidenceGraphView";
import { KnowledgeOutlineView } from "./KnowledgeOutlineView";
import { TaskOutlineView } from "./TaskOutlineView";
import type { NormalizedAssetRef, TaskOutlineEnvelope } from "@/lib/api";

const SHOW_EVIDENCE_GRAPH = false as const;

type Props = {
  normalizedRef: NormalizedAssetRef | null;
  initialTaskOutline?: TaskOutlineEnvelope | null;
  taskOutlineOk?: boolean;
  taskOutlineError?: string | null;
  taskOutlineTraceId?: string | null;
  // Forwarded from AssetDetailTabs — invoked by KnowledgeOutlineView
  // to jump the "原文预览" tab to a specific block.
  onJumpToBlock?: (blockId: string) => void;
};

type ViewKey = "chunks" | "knowledge_outline" | "task_outline";

const CHUNK_VIEW_OPTION = { label: "RAG知识块", value: "chunks" as const };
// theory_knowledge textbooks get the persisted 3-level knowledge outline.
const KNOWLEDGE_OUTLINE_VIEW_OPTION = {
  label: "知识点大纲",
  value: "knowledge_outline" as const,
};
const TASK_OUTLINE_VIEW_OPTION = { label: "任务大纲", value: "task_outline" as const };

export function DocumentKnowledgeView({
  normalizedRef,
  initialTaskOutline = null,
  taskOutlineOk = true,
  taskOutlineError = null,
  taskOutlineTraceId = null,
  onJumpToBlock,
}: Props) {
  const [view, setView] = useState<ViewKey>("chunks");
  const normalizedRefId = normalizedRef?.id ?? null;
  const taskProfile = initialTaskOutline?.profile ?? null;
  const graphAdmission = taskProfile?.evidence_graph_admission ?? null;
  const showKnowledgeOutline =
    taskOutlineOk && taskProfile?.textbook_subtype === "theory_knowledge";
  const showTaskOutline =
    taskOutlineOk &&
    taskProfile?.processing_profile === "task_outline" &&
    taskProfile?.textbook_subtype === "training_operation";
  // Evidence Graph currently hidden (block-level extraction too fine).
  // graphAdmission is still tracked for future re-enable.
  void graphAdmission;

  const viewOptions: Array<{ label: string; value: ViewKey }> = [
    CHUNK_VIEW_OPTION,
    ...(showKnowledgeOutline ? [KNOWLEDGE_OUTLINE_VIEW_OPTION] : []),
    ...(showTaskOutline ? [TASK_OUTLINE_VIEW_OPTION] : []),
  ];

  useEffect(() => {
    if (view === "knowledge_outline" && !showKnowledgeOutline) {
      setView("chunks");
    }
    if (view === "task_outline" && !showTaskOutline) {
      setView("chunks");
    }
  }, [showKnowledgeOutline, showTaskOutline, view]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <Segmented
          value={view}
          onChange={(value) => setView(value as ViewKey)}
          options={viewOptions}
          aria-label="切换文档知识块视图"
        />
      </div>

      {view === "chunks" ? (
        <ChunkListSection
          refId={normalizedRefId}
          title="RAG知识块"
          emptyDescription="该 ref 暂未生成 RAG 语义知识块。"
          mode="preview"
          actionLabel="定位原文"
        />
      ) : null}
      {view === "knowledge_outline" && showKnowledgeOutline ? (
        <KnowledgeOutlineView
          refId={normalizedRefId}
          isTheoryKnowledge={showKnowledgeOutline}
          onJumpToBlock={onJumpToBlock}
        />
      ) : null}
      {view === "task_outline" && showTaskOutline ? (
        <TaskOutlineView
          refId={normalizedRefId}
          initialData={initialTaskOutline}
          initialError={
            taskOutlineOk
              ? null
              : `${taskOutlineError ?? "任务大纲加载失败"}${taskOutlineTraceId ? `（trace ${taskOutlineTraceId}）` : ""}`
          }
        />
      ) : null}
      {/* Evidence Graph view temporarily hidden — see SHOW_EVIDENCE_GRAPH */}
      {SHOW_EVIDENCE_GRAPH ? null : null}
    </div>
  );
}
