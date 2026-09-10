"use client";

import { useState } from "react";
import { Segmented } from "antd";
import { ChunkListSection } from "./ChunkListSection";
import { CapabilityGraphView } from "./CapabilityGraphView";
import type { CapabilityGraphBuildType } from "./CapabilityGraphView";

type View = "chunks" | "graph";
type TeachingStandardGraphBuildType = Extract<
  CapabilityGraphBuildType,
  "teaching_standard" | "course_standard"
>;

export function TeachingStandardKnowledgeView({
  normalizedRefId,
  graphBuildType,
}: {
  normalizedRefId: string;
  graphBuildType: TeachingStandardGraphBuildType;
}) {
  const [view, setView] = useState<View>("chunks");
  const graphTitle = graphBuildType === "course_standard" ? "课程知识图谱" : "岗位知识图谱";
  const viewOptions = [
    { label: "知识块", value: "chunks" },
    ...(graphBuildType === "course_standard" ? [{ label: graphTitle, value: "graph" }] : []),
  ];
  return (
    <div className="flex flex-col gap-4">
      {viewOptions.length > 1 ? (
        <div className="flex justify-end">
          <Segmented
            value={view}
            onChange={(value) => setView(value as View)}
            options={viewOptions}
            aria-label="切换教学标准知识视图"
          />
        </div>
      ) : null}
      {view === "chunks" ? (
        <ChunkListSection
          refId={normalizedRefId}
          title="知识块"
          emptyDescription="该教学标准暂未生成语义知识块。"
          mode="preview"
          actionLabel="定位原文"
          knowledgeTypeCode="course_standard_authoring_process"
        />
      ) : null}
      {view === "graph" && graphBuildType === "course_standard" ? (
        <CapabilityGraphView
          normalizedRefId={normalizedRefId}
          buildType={graphBuildType}
          title={graphTitle}
        />
      ) : null}
    </div>
  );
}
