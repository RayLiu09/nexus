import { PageScaffold } from "@/components/PageScaffold";

export default function IamAuditPage() {
  return (
    <PageScaffold
      title="权限与审计"
      prototypeId="NX-10"
      summary="本地组织用户、角色、API Key、组织范围、审批和审计日志。"
      columns={["对象", "权限范围", "组织范围", "状态", "更新时间", "操作"]}
      statuses={["active", "enabled", "disabled", "archived"]}
      primaryAction="新建 API Key"
    />
  );
}
