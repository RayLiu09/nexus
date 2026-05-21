import { PageHeader } from "@/components/PageHeader";
import TagReviewContent from "./_components/TagReviewContent";
import { Button } from "antd";

export const dynamic = "force-dynamic";

export default function TagReviewPage() {
  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — normalized asset 标签运营"
        title="标签审核"
        description="标签生成在 metadata_enrich 阶段针对 normalized asset 执行。高置信自动提交并写审计；低置信进入人工审核。"
        actions={
          <Button type="primary" href="/governance">
            返回治理中心
          </Button>
        }
      />
      <TagReviewContent />
    </>
  );
}
