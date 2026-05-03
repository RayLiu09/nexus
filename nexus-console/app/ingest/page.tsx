import { PageScaffold } from "@/components/PageScaffold";

export default function IngestPage() {
  return (
    <PageScaffold
      title="数据接入"
      prototypeId="NX-03"
      summary="单文件、批量、目录导入和批次提交。"
      columns={["文件名", "大小", "类型", "校验状态", "重复判定", "操作"]}
      statuses={["submitted", "raw_persisted", "duplicate_skipped", "checksum_failed"]}
      primaryAction="提交批次"
    />
  );
}
