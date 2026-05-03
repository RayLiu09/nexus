import { PageScaffold } from "@/components/PageScaffold";

export default function JobsPage() {
  return (
    <PageScaffold
      title="作业中心"
      prototypeId="NX-05"
      summary="查看异步处理状态、失败原因、重试、重处理和重治理。"
      columns={["作业ID", "类型", "关联对象", "阶段", "状态", "耗时", "重试", "创建时间", "操作"]}
      statuses={["queued", "running", "succeeded", "failed", "review_required", "dead_lettered"]}
    />
  );
}
