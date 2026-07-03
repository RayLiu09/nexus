"use client";

import { useState } from "react";
import { Segmented } from "antd";

import { ChunkListSection } from "./ChunkListSection";
import { EvidenceGraphView } from "./EvidenceGraphView";
import { TaskOutlineView } from "./TaskOutlineView";
import type { NormalizedAssetRef } from "@/lib/api";

type Props = {
  normalizedRef: NormalizedAssetRef | null;
};

type ViewKey = "chunks" | "task_outline" | "evidence_graph";

const VIEW_OPTIONS: Array<{ label: string; value: ViewKey }> = [
  { label: "RAG知识块", value: "chunks" },
  { label: "任务大纲", value: "task_outline" },
  { label: "Evidence Graph", value: "evidence_graph" },
];

export function DocumentKnowledgeView({ normalizedRef }: Props) {
  const [view, setView] = useState<ViewKey>("chunks");
  const normalizedRefId = normalizedRef?.id ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <Segmented
          value={view}
          onChange={(value) => setView(value as ViewKey)}
          options={VIEW_OPTIONS}
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
      {view === "task_outline" ? <TaskOutlineView refId={normalizedRefId} /> : null}
      {view === "evidence_graph" ? <EvidenceGraphView normalizedRef={normalizedRef} /> : null}
    </div>
  );
}
