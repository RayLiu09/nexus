import { PageScaffold } from "@/components/PageScaffold";

export default function WorkbenchPage() {
  return (
    <PageScaffold
      title="工作台"
      prototypeId="NX-01"
      summary="接入、作业、治理、规则和基础运行状态总览。"
      columns={["批次号", "来源", "对象数", "成功", "失败", "状态", "创建时间"]}
      statuses={["raw_persisted", "running", "review_required", "failed"]}
    />
  );
}
