import { PageScaffold } from "@/components/PageScaffold";

export default function RulesPage() {
  return (
    <PageScaffold
      title="规则配置"
      prototypeId="NX-09"
      summary="规则集、规则、校验、发布、回滚和治理决策追踪。"
      columns={["规则集名称", "类型", "版本", "状态", "规则数", "发布人", "更新时间", "操作"]}
      statuses={["draft", "validating", "published", "validation_failed", "disabled", "archived"]}
      primaryAction="新建规则集"
    />
  );
}
