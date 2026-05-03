import { PageScaffold } from "@/components/PageScaffold";

export default function RawLedgerPage() {
  return (
    <PageScaffold
      title="原始数据台账"
      prototypeId="NX-04"
      summary="查询接入批次和原始对象，验证原始留存、checksum 和回放入口。"
      columns={["批次号", "数据源", "对象数", "成功", "失败", "状态", "操作"]}
      statuses={["raw_persisted", "checksum_failed", "duplicate_skipped", "failed"]}
    />
  );
}
