import type { StatusValue } from "@/lib/status";

export const week2Demo = {
  batchId: "bat-m1-static-001",
  rawObjectId: "raw-m1-static-001",
  jobId: "job-m1-ingest-001",
  assetId: "demo-asset",
  versionId: "ver-m1-001",
  parseArtifactId: "pa-m1-001",
  normalizedRefId: "ref-m1-001",
  title: "D4 静态知识文档样本",
  source: "D4 Upload",
  objectUri: "s3://nexus-dev-objects/raw/file_upload/d4-demo/2026/05/04/sample.pdf",
  artifactUri: "s3://nexus-dev-objects/parsed/ver-m1-001/pa-m1-001/mineru-result.json",
  normalizedUri:
    "s3://nexus-dev-objects/normalized/document/ver-m1-001/ref-m1-001/schema-v1/8ab2c4d6.json",
  checksum: "sha256:8ab2c4d6...",
  createdAt: "2026-05-04 10:30"
};

export type DemoRow = {
  label: string;
  values: string[];
  status?: StatusValue;
};

export const jobStages: DemoRow[] = [
  {
    label: "资产化",
    values: ["assetize", week2Demo.assetId, week2Demo.versionId],
    status: "succeeded"
  },
  {
    label: "MinerU 解析",
    values: ["parse", week2Demo.rawObjectId, week2Demo.parseArtifactId],
    status: "succeeded"
  },
  {
    label: "标准化",
    values: ["normalize", week2Demo.versionId, week2Demo.normalizedRefId],
    status: "succeeded"
  }
];
