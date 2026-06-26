/**
 * Mock catalogue for the `/data-assets` board.
 *
 * Six top-level "domains" map 1:1 to the `--domain-d1 … --domain-d6` colour
 * tokens already declared in `app/globals.css`. The page swaps this for the
 * real backend feed once `nexus-api` ships the aggregate endpoint — fields
 * mirror what that endpoint will return (totals, freshness, blockers).
 */

export type Subcategory = {
  /** Stable code aligned with governance_rules.json classification codes. */
  code: string;
  /** Display name in zh-CN. */
  name: string;
  /** Latin / English shadow line for the editorial subtitle. */
  shadow: string;
  /** Total record count for this subclass. */
  count: number;
  /** Records ingested or refreshed in the last 7 days. */
  fresh: number;
  /** Records currently parked in review_required. */
  review: number;
};

export type DomainDelta = {
  /** Signed percentage change over the previous comparison window. */
  pct: number;
  /** Comparison window label, e.g. "vs last week". */
  label: string;
};

export type DomainCard = {
  /** Slot code D1 … D6 — drives the accent colour via `--domain-d{n}` token. */
  slot: 1 | 2 | 3 | 4 | 5 | 6;
  /** Stable code (e.g. "D1") used as a watermark + breadcrumb. */
  code: string;
  /** Display name of the top-level domain. */
  name: string;
  /** Editorial Latin caption shown under the Chinese name. */
  shadow: string;
  /** One-line editorial summary. */
  caption: string;
  /** Total record count rolled up from `sub[*].count`. */
  total: number;
  /** Records currently parked in review_required (rolled up). */
  review: number;
  /** Delta versus the prior window — used in the trend chip. */
  delta: DomainDelta;
  /** Subcategory ledger entries — render order is preserved. */
  sub: Subcategory[];
};

/** Board-level aggregates that sit in the masthead. */
export type BoardOverview = {
  /** Total record count across every domain. */
  totalRecords: number;
  /** Distinct asset count across every domain. */
  totalAssets: number;
  /** Records refreshed (added or re-ingested) in the last 7 days. */
  weeklyFresh: number;
  /** Aggregate review_required count. */
  totalReview: number;
  /** Number of distinct top-level domain classifications represented. */
  domainCount: number;
  /** ISO 8601 instant the snapshot was produced. Mocked to today. */
  generatedAt: string;
  /** Synthetic issue number — purely editorial. */
  issueNo: string;
};


export const BOARD_OVERVIEW: BoardOverview = {
  totalRecords: 23_812,
  totalAssets: 1_487,
  weeklyFresh: 612,
  totalReview: 47,
  domainCount: 6,
  generatedAt: new Date("2026-06-26T08:00:00+08:00").toISOString(),
  issueNo: "VOL.01 · ISSUE.07",
};


export const DOMAIN_CARDS: DomainCard[] = [
  {
    slot: 1,
    code: "D1",
    name: "产业 / 行业数据",
    shadow: "Industry & Sector Intelligence",
    caption:
      "覆盖国家与地方产业政策、第三方机构产业 / 行业研究报告，是平台对外行业洞察的事实底座。",
    total: 1487,
    review: 12,
    delta: { pct: 12.3, label: "vs 上周" },
    sub: [
      { code: "industry_policy", name: "产业政策",
        shadow: "Industrial Policy", count: 234, fresh: 12, review: 3 },
      { code: "industry_report", name: "产业报告",
        shadow: "Industrial Report", count: 658, fresh: 41, review: 5 },
      { code: "sector_report", name: "行业报告",
        shadow: "Sector Report", count: 595, fresh: 27, review: 4 },
    ],
  },
  {
    slot: 2,
    code: "D2",
    name: "岗位与职业数据",
    shadow: "Job & Occupation Records",
    caption:
      "招聘平台爬取的岗位需求 / PGSD 模型的职业能力分析 / 行业认可的职业证书三方汇聚。",
    total: 3_124,
    review: 18,
    delta: { pct: 8.1, label: "vs 上周" },
    sub: [
      { code: "job_demand", name: "岗位需求数据",
        shadow: "Job Demand Records", count: 2_587, fresh: 312, review: 12 },
      { code: "competency_analysis", name: "职业能力分析",
        shadow: "Competency Analysis", count: 132, fresh: 4, review: 2 },
      { code: "vocational_certificate", name: "职业类证书",
        shadow: "Vocational Certificate", count: 405, fresh: 19, review: 4 },
    ],
  },
  {
    slot: 3,
    code: "D3",
    name: "教学与专业数据",
    shadow: "Teaching & Major Catalogue",
    caption:
      "专业目录、教学标准与各高校专业布点数 — 用于产学衔接与培养计划编排。",
    total: 4_269,
    review: 6,
    delta: { pct: 2.4, label: "vs 上周" },
    sub: [
      { code: "teaching_standard", name: "专业教学标准",
        shadow: "Teaching Standard", count: 1_812, fresh: 23, review: 2 },
      { code: "major_distribution", name: "专业布点数",
        shadow: "Program Distribution", count: 1_956, fresh: 18, review: 2 },
      { code: "program_profile", name: "专业简介",
        shadow: "Program Profile", count: 501, fresh: 7, review: 2 },
    ],
  },
  {
    slot: 4,
    code: "D4",
    name: "人才培养数据",
    shadow: "Talent Cultivation",
    caption:
      "人才需求报告 + 人才培养方案，连接外部需求与内部教学供给。",
    total: 982,
    review: 4,
    delta: { pct: -1.7, label: "vs 上周" },
    sub: [
      { code: "talent_demand_report", name: "专业人才需求报告",
        shadow: "Talent Demand Report", count: 537, fresh: 8, review: 1 },
      { code: "talent_training_plan", name: "人才培养方案",
        shadow: "Talent Training Plan", count: 445, fresh: 5, review: 3 },
    ],
  },
  {
    slot: 5,
    code: "D5",
    name: "政策与标准",
    shadow: "Policy & Standards",
    caption:
      "国家与地方的政策法规、行业标准、质量标准 — 治理决策合规依据。",
    total: 6_487,
    review: 5,
    delta: { pct: 4.6, label: "vs 上周" },
    sub: [
      { code: "policy_regulation", name: "政策法规",
        shadow: "Policy & Regulation", count: 3_124, fresh: 64, review: 2 },
      { code: "industry_standard", name: "行业标准",
        shadow: "Industry Standard", count: 2_058, fresh: 36, review: 1 },
      { code: "quality_standard", name: "质量标准",
        shadow: "Quality Standard", count: 1_305, fresh: 22, review: 2 },
    ],
  },
  {
    slot: 6,
    code: "D6",
    name: "综合管理 / 运营",
    shadow: "Administration & Operation",
    caption:
      "企业基础信息、运营 / 财务报告、内部规章 — 平台基础运维与审计依据。",
    total: 7_463,
    review: 2,
    delta: { pct: 0.3, label: "vs 上周" },
    sub: [
      { code: "enterprise_basic", name: "企业基础数据",
        shadow: "Enterprise Basic", count: 2_984, fresh: 18, review: 0 },
      { code: "business_operation", name: "业务运营数据",
        shadow: "Business Operation", count: 3_417, fresh: 42, review: 1 },
      { code: "administrative_doc", name: "管理 / 制度文件",
        shadow: "Administrative Doc", count: 1_062, fresh: 9, review: 1 },
    ],
  },
];
