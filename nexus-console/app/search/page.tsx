import { PageHeader } from "@/components/PageHeader";
import { Empty } from "@/components/shared/Empty";
import { Button } from "antd";

export const dynamic = "force-dynamic";

export default function SearchPage() {
  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — 检索与问答验证"
        title="检索验证"
        description="消费侧验证页面，确认权限过滤、引用追溯和 QA 审计可用。平台验收和调优入口，不是最终用户搜索门户。"
      />

      <Empty
        title="检索验证页骨架建设中"
        description="阶段 P2.13 落地：query 构造、权限切换、结果与引用追溯。"
        actions={
          <Button type="default" href="/iam-audit">
            前往权限与审计
          </Button>
        }
      />
    </>
  );
}
