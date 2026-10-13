"use client";

import { Badge, Card, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TagDimensionRow, TagRuleDetail } from "../_lib/tagDimensions";

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

type DimensionRow = {
  name: string;
  weight: number;
  check_items: unknown[];
  description: string;
};

interface RulesReadViewProps {
  classifications: ClassificationRow[];
  levels: LevelRow[];
  tagDimensions: TagDimensionRow[];
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
        <div className="space-y-1 text-xs leading-5 text-[var(--text-muted)]">
          {criteria.map((item, index) => <div key={`${index}-${item}`}>{item}</div>)}
        </div>
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

const TAG_DIMENSION_COLUMNS: ColumnsType<TagDimensionRow> = [
  {
    title: "维度",
    dataIndex: "name",
    width: 170,
    render: (name: string, row) => <><strong>{name}</strong><div className="text-xs text-[var(--text-muted)]">{row.code}</div></>,
  },
  {
    title: "来源",
    dataIndex: "source",
    width: 110,
    render: (source: string) => source === "fixed" ? "固定选项" : "按分类打标",
  },
  {
    title: "选项 / 依据",
    render: (_, row) => <div className="space-y-1 text-xs leading-5">
      {row.description && <div>{row.description}</div>}
      {row.values.map((value) => <div key={value}>{value}</div>)}
      {row.details.length > 0 && <span className="text-[var(--text-muted)]">{row.details.length} 个分类有打标依据</span>}
    </div>,
  },
];

const TAG_DETAIL_COLUMNS: ColumnsType<TagRuleDetail> = [
  { title: "适用分类", dataIndex: "classification", width: 180 },
  { title: "选项与判断标准", dataIndex: "criteria", render: (criteria: string[]) => (
    <div className="space-y-1 text-xs leading-5">
      {criteria.map((item, index) => <div key={`${index}-${item}`}>{item}</div>)}
    </div>
  ) },
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
  tagDimensions,
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
            <span>数据标签（tag_dimensions）</span>
            <Badge count={tagDimensions.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<TagDimensionRow>
          rowKey="code"
          dataSource={tagDimensions}
          pagination={false}
          size="middle"
          columns={TAG_DIMENSION_COLUMNS}
          expandable={{
            rowExpandable: (row) => row.details.length > 0,
            expandedRowRender: (row) => <Table<TagRuleDetail>
              rowKey="code"
              dataSource={row.details}
              columns={TAG_DETAIL_COLUMNS}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              size="small"
            />,
          }}
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
