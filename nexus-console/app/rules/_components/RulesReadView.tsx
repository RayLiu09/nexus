"use client";

import { Badge, Card, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

type ClassificationRow = {
  code: string;
  name: string;
  criteria: string[];
};

type LevelRow = {
  code: string;
  name: string;
  requires_approval: boolean;
  forbid_external_llm: boolean;
  criteria: string[];
};

type TagRow = {
  code: string;
  name: string;
  applicable_classifications: string[];
  criteria: string[];
};

type DimensionRow = {
  name: string;
  weight: number;
  check_items: unknown[];
  description: string;
};

interface RulesReadViewProps {
  classifications: ClassificationRow[];
  levels: LevelRow[];
  tags: TagRow[];
  dimensions: DimensionRow[];
  thresholds: Record<string, unknown> | null;
  autoAdoptThreshold: number | string | null;
}

const CLASSIFICATION_COLUMNS: ColumnsType<ClassificationRow> = [
  {
    title: "Code",
    dataIndex: "code",
    width: 110,
    render: (code: string) => <Tag color="purple">{code}</Tag>,
  },
  { title: "名称", dataIndex: "name", width: 200 },
  {
    title: "判断标准",
    dataIndex: "criteria",
    render: (criteria: string[]) =>
      criteria.length > 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{criteria.join("；")}</span>
      ) : (
        "-"
      ),
  },
];

const LEVEL_COLUMNS: ColumnsType<LevelRow> = [
  {
    title: "Code",
    dataIndex: "code",
    width: 90,
    render: (code: string) => {
      const dangerous = code === "L3" || code === "L4";
      return <Tag color={dangerous ? "error" : "default"}>{code}</Tag>;
    },
  },
  { title: "名称", dataIndex: "name", width: 180 },
  {
    title: "需审批",
    dataIndex: "requires_approval",
    width: 90,
    render: (v: boolean) => (v ? "是" : "否"),
  },
  {
    title: "禁外部 LLM",
    dataIndex: "forbid_external_llm",
    width: 110,
    render: (v: boolean) => (v ? "是" : "-"),
  },
  {
    title: "判断标准",
    dataIndex: "criteria",
    render: (criteria: string[]) =>
      criteria.length > 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{criteria.join("；")}</span>
      ) : (
        "-"
      ),
  },
];

const TAG_COLUMNS: ColumnsType<TagRow> = [
  {
    title: "Code",
    dataIndex: "code",
    width: 140,
    render: (code: string) => <Tag>{code}</Tag>,
  },
  { title: "名称", dataIndex: "name", width: 180 },
  {
    title: "适用分类",
    dataIndex: "applicable_classifications",
    width: 200,
    render: (xs: string[]) =>
      xs.length > 0 ? (
        <span className="text-xs">{xs.join(", ")}</span>
      ) : (
        <span className="text-xs text-[var(--text-muted)]">通用</span>
      ),
  },
  {
    title: "判断标准",
    dataIndex: "criteria",
    render: (criteria: string[]) =>
      criteria.length > 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{criteria.join("；")}</span>
      ) : (
        "-"
      ),
  },
];

const DIMENSION_COLUMNS: ColumnsType<DimensionRow> = [
  {
    title: "维度",
    dataIndex: "name",
    width: 160,
    render: (n: string) => <strong>{n}</strong>,
  },
  {
    title: "权重",
    dataIndex: "weight",
    width: 90,
    render: (w: number) => `${(w * 100).toFixed(0)}%`,
  },
  {
    title: "检查项数",
    dataIndex: "check_items",
    width: 100,
    render: (items: unknown[]) => items.length,
  },
  {
    title: "说明",
    dataIndex: "description",
    render: (d: string) => (
      <span className="text-xs text-[var(--text-muted)]">{d || "-"}</span>
    ),
  },
];

export function RulesReadView({
  classifications,
  levels,
  tags,
  dimensions,
  thresholds,
  autoAdoptThreshold,
}: RulesReadViewProps) {
  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <Card
        title={
          <Space>
            <span>数据域分类（classification）</span>
            <Badge count={classifications.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<ClassificationRow>
          rowKey="code"
          dataSource={classifications}
          pagination={false}
          size="middle"
          columns={CLASSIFICATION_COLUMNS}
        />
      </Card>

      <Card
        title={
          <Space>
            <span>数据分级（level）</span>
            <Badge count={levels.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<LevelRow>
          rowKey="code"
          dataSource={levels}
          pagination={false}
          size="middle"
          columns={LEVEL_COLUMNS}
        />
      </Card>

      <Card
        title={
          <Space>
            <span>数据标签（tags）</span>
            <Badge count={tags.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<TagRow>
          rowKey="code"
          dataSource={tags}
          pagination={false}
          size="middle"
          columns={TAG_COLUMNS}
        />
      </Card>

      <Card
        title={
          <Space>
            <span>质量评分维度（quality_scoring）</span>
            <Badge count={dimensions.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<DimensionRow>
          rowKey="name"
          dataSource={dimensions}
          pagination={false}
          size="middle"
          columns={DIMENSION_COLUMNS}
        />
        {thresholds && (
          <Typography.Paragraph type="secondary" className="!mt-3 !mb-0 text-detail">
            通过阈值：≥{String(thresholds.pass ?? "-")} 分 ｜ 预警：≥
            {String(thresholds.warning ?? "-")} 分 ｜ 复核线：&lt;
            {String(thresholds.review_required_below ?? "-")} 分 ｜ AI 自动采纳置信度：
            {autoAdoptThreshold ?? "-"}
          </Typography.Paragraph>
        )}
      </Card>
    </Space>
  );
}
