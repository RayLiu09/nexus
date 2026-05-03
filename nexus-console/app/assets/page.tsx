import { PageScaffold } from "@/components/PageScaffold";

export default function AssetsPage() {
  return (
    <PageScaffold
      title="资产目录"
      prototypeId="NX-06"
      summary="资产列表、派生当前版本、版本、标准化引用和索引状态。"
      columns={["标题", "数据域", "类型", "分级", "标签", "当前版本", "AI采纳", "质量", "索引", "状态", "操作"]}
      statuses={["available", "review_required", "processing", "archived", "disabled", "failed"]}
      primaryAction="上传资产"
    />
  );
}
