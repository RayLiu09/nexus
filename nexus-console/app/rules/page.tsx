import { PageScaffold } from "@/components/PageScaffold";

export default function RulesPage() {
  return (
    <PageScaffold
      title="规则配置"
      prototypeId="NX-09"
      summary="规则集、规则、受限表达式校验、保存即生效和治理决策追踪。"
      columns={["规则集名称", "类型", "版本", "状态", "规则数", "更新人", "更新时间", "操作"]}
      statuses={["active", "disabled"]}
      primaryAction="新建规则集"
    />
  );
}
