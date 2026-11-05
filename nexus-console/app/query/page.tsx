import { PageHeader } from "@/components/PageHeader";

import { QueryPlayground } from "./_components/QueryPlayground";

export const dynamic = "force-dynamic";

export default function QueryRouterV2Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="NEXUS AI"
        title="智能检索"
        description="用自然语言查询数据与知识，实时查看执行过程，追溯每一条回答的来源。"
      />
      <QueryPlayground />
    </div>
  );
}
