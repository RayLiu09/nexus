"use client";

import { useEffect, useState } from "react";
import { Segmented } from "antd";

import { ChunkListSection } from "./ChunkListSection";
import { EvidenceGraphView } from "./EvidenceGraphView";
import { TaskOutlineView } from "./TaskOutlineView";
import type { NormalizedAssetRef, TaskOutlineEnvelope } from "@/lib/api";

type Props = {
  normalizedRef: NormalizedAssetRef | null;
  initialTaskOutline?: TaskOutlineEnvelope | null;
  taskOutlineOk?: boolean;
  taskOutlineError?: string | null;
  taskOutlineTraceId?: string | null;
};

type ViewKey = "chunks" | "task_outline" | "evidence_graph";

const BASE_VIEW_OPTIONS: Array<{ label: string; value: ViewKey }> = [
  { label: "RAG知识块", value: "chunks" },
  { label: "任务大纲", value: "task_outline" },
];

export function DocumentKnowledgeView({
  normalizedRef,
  initialTaskOutline = null,
  taskOutlineOk = true,
  taskOutlineError = null,
  taskOutlineTraceId = null,
}: Props) {
  const [view, setView] = useState<ViewKey>("chunks");
  const normalizedRefId = normalizedRef?.id ?? null;
  const graphAdmission = initialTaskOutline?.profile?.evidence_graph_admission ?? null;
  const showEvidenceGraph =
    taskOutlineOk && (graphAdmission === null || graphAdmission === "recommended");
  const viewOptions = showEvidenceGraph
    ? [...BASE_VIEW_OPTIONS, { label: "Evidence Graph", value: "evidence_graph" as const }]
    : BASE_VIEW_OPTIONS;

  useEffect(() => {
    if (view === "evidence_graph" && !showEvidenceGraph) {
      setView("chunks");
    }
  }, [showEvidenceGraph, view]);

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
      {view === "task_outline" ? (
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
      {view === "evidence_graph" ? <EvidenceGraphView normalizedRef={normalizedRef} /> : null}
    </div>
  );
}
