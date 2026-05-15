const STAGES = [
  "接入校验",
  "解析完成",
  "资产化完成",
  "标准化处理中",
  "AI治理待执行",
  "规则待执行",
  "索引待执行",
  "完成"
];

type StageStatus = "done" | "active" | "pending" | "failed";

type JobPipelineProps = {
  stages: { name: string; status: StageStatus; detail?: string }[];
  currentStage?: string;
};

function stageClass(status: StageStatus): string {
  if (status === "done") return "done";
  if (status === "active") return "active";
  if (status === "failed") return "failed";
  return "";
}

export function JobPipeline({ stages, currentStage }: JobPipelineProps) {
  return (
    <div className="m1-flow">
      {stages.map((stage, i) => (
        <span key={i} className={stageClass(stage.status)} title={stage.detail}>
          {stage.status === "active" ? "◉ " : stage.status === "done" ? "✓ " : ""}
          {stage.name}
          {stage.status === "active" && (
            <span className="text-xs text-muted" style={{ display: "block" }}>
              {stage.detail ?? "进行中..."}
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

/** Default pipeline for P0 document flow */
export function DefaultDocPipeline({
  currentStage
}: {
  currentStage?: string;
}) {
  const allStages = [
    "ingest_validate",
    "document_parse",
    "assetize",
    "normalize",
    "ai_governance",
    "rule_guard",
    "index",
    "complete"
  ];

  const stageLabels: Record<string, string> = {
    ingest_validate: "接入校验",
    document_parse: "解析",
    assetize: "资产化",
    normalize: "标准化",
    ai_governance: "AI治理",
    rule_guard: "规则质检",
    index: "索引",
    complete: "完成"
  };

  const currentIdx = currentStage ? allStages.indexOf(currentStage) : -1;

  const stages = allStages.map((key, i) => {
    const label = stageLabels[key] ?? key;
    let status: StageStatus = "pending";
    if (i < currentIdx) status = "done";
    else if (i === currentIdx) status = "active";
    else status = "pending";
    return { name: label, status };
  });

  return <JobPipeline stages={stages} currentStage={currentStage} />;
}
