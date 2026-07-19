import { PageHeader } from "@/components/PageHeader";

import { QueryPlayground } from "./_components/QueryPlayground";

export const dynamic = "force-dynamic";

export default function QueryRouterV2Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Query Router v2"
        title="智能检索"
        description="三层 LLM 编排：意图分类 → 参数抽取 + 工具编排 → Markdown 汇总；来源引用、生成段落与图谱数据自动区分。"
      />
      <QueryPlayground />
    </div>
  );
}
