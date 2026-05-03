import { PageScaffold } from "@/components/PageScaffold";

export default function GovernancePage() {
  return (
    <PageScaffold
      title="治理中心"
      prototypeId="NX-08"
      summary="AI 治理建议、AI 质量评分、治理待办、规则配置入口、决策追踪、质量复核和人工覆盖。"
      columns={["资产", "版本", "AI采纳", "复核原因", "命中规则", "质量分", "状态", "操作"]}
      statuses={["auto_adopted", "partially_adopted", "review_required", "rejected", "overridden"]}
    />
  );
}
