import { PageScaffold } from "@/components/PageScaffold";

export default function DataSourcesPage() {
  return (
    <PageScaffold
      title="数据源管理"
      prototypeId="NX-02"
      summary="数据源注册、上传入口、NAS 同步和爬虫推送配置。"
      columns={["名称", "类型", "业务域提示", "分级提示", "组织提示", "最近同步", "状态", "操作"]}
      statuses={["enabled", "disabled", "error"]}
      primaryAction="新建数据源"
    />
  );
}
