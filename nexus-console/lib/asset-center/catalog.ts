import type { LucideIcon } from "lucide-react";
import { Activity, BookOpenText, BriefcaseBusiness, GraduationCap, Landmark } from "lucide-react";

export type AssetCenterResource = {
  path: string;
  name: string;
  description: string;
  classificationCode?: string;
};

export type AssetCenterDomain = {
  slug: string;
  name: string;
  description: string;
  icon: LucideIcon;
  accent: string;
  accentBackground: string;
  resources: readonly AssetCenterResource[];
};

export const ASSET_CENTER_DOMAINS = [
  {
    slug: "policy",
    name: "产业政策数据",
    description: "产业与教育政策、产业报告和行业报告",
    icon: Landmark,
    accent: "#166534",
    accentBackground: "#f0fdf4",
    resources: [
      {
        path: "industry-policies",
        name: "产业政策",
        description: "国家、省级和区域产业政策",
        classificationCode: "industry_policy",
      },
      {
        path: "education-policies",
        name: "教育政策",
        description: "国家、省级和区域教育政策",
        classificationCode: "education_policy",
      },
      {
        path: "industry-reports",
        name: "产业报告",
        description: "产业规模、结构和发展趋势报告",
        classificationCode: "industry_report",
      },
      {
        path: "sector-reports",
        name: "行业报告",
        description: "行业运行、市场和趋势研究报告",
        classificationCode: "sector_report",
      },
    ],
  },
  {
    slug: "major",
    name: "专业数据",
    description: "专业建设、标准、课程与人才培养数据",
    icon: GraduationCap,
    accent: "#1d4ed8",
    accentBackground: "#eff6ff",
    resources: [
      {
        path: "profiles",
        name: "专业简介",
        description: "院校与标准专业基本信息",
        classificationCode: "major_profile",
      },
      {
        path: "distributions",
        name: "专业布点数据",
        description: "跨地区、年度和专业的布点记录",
        classificationCode: "major_distribution",
      },
      {
        path: "teaching-standards",
        name: "专业教学标准",
        description: "按专业查看教学标准",
        classificationCode: "teaching_standard",
      },
      {
        path: "standard-course-library",
        name: "标准课程库",
        description: "跨专业浏览课程记录及其开设专业",
        classificationCode: "teaching_standard",
      },
      {
        path: "talent-demand-reports",
        name: "专业人才需求报告",
        description: "专业人才需求及供需分析报告",
        classificationCode: "talent_demand_report",
      },
      {
        path: "training-plans",
        name: "人才培养方案",
        description: "院校专业人才培养方案",
        classificationCode: "talent_training_plan",
      },
      {
        path: "occupation-analyses",
        name: "职业能力分析",
        description: "职业任务和能力要求分析",
        classificationCode: "competency_analysis",
      },
    ],
  },
  {
    slug: "market",
    name: "市场数据",
    description: "岗位、园区、企业与市场认可证书数据",
    icon: BriefcaseBusiness,
    accent: "#b45309",
    accentBackground: "#fffbeb",
    resources: [
      {
        path: "job-demands",
        name: "岗位需求数据",
        description: "跨来源岗位需求记录",
        classificationCode: "job_demand",
      },
      {
        path: "industrial-parks",
        name: "产业园区数据",
        description: "产业园区业务数据",
      },
      {
        path: "enterprises",
        name: "企业数据",
        description: "企业主体与经营业务数据",
      },
      {
        path: "certificates",
        name: "证书数据",
        description: "跨来源职业证书数据",
        classificationCode: "vocational_certificate",
      },
    ],
  },
  {
    slug: "teaching-resources",
    name: "教材资源数据",
    description: "教材、教学案例和课程标准资源",
    icon: BookOpenText,
    accent: "#9f1239",
    accentBackground: "#fff1f2",
    resources: [
      {
        path: "theory-textbooks",
        name: "理论教材",
        description: "以理论知识体系为主的教材",
        classificationCode: "course_textbook",
      },
      {
        path: "training-textbooks",
        name: "实训教材",
        description: "以项目、任务和实训过程为主的教材",
        classificationCode: "course_textbook",
      },
      {
        path: "cases",
        name: "教学案例",
        description: "跨来源教学案例库",
      },
      {
        path: "course-standards",
        name: "课程标准",
        description: "课程目标、内容与实施要求",
      },
    ],
  },
  {
    slug: "user-behavior",
    name: "用户行为数据",
    description: "能力评价、学习过程与学情分析数据",
    icon: Activity,
    accent: "#0f766e",
    accentBackground: "#f0fdfa",
    resources: [
      {
        path: "ability-indicators",
        name: "能力指标库",
        description: "学习与职业能力指标",
      },
      {
        path: "scoring-systems",
        name: "评分体系库",
        description: "能力与学习评价评分体系",
      },
      {
        path: "learning-records",
        name: "学习数据",
        description: "学习过程和结果记录",
      },
      {
        path: "learning-analytics",
        name: "学情分析",
        description: "学习状态与发展分析",
      },
    ],
  },
] as const satisfies readonly AssetCenterDomain[];

export function findAssetCenterDomain(slug: string): AssetCenterDomain | undefined {
  return ASSET_CENTER_DOMAINS.find((domain) => domain.slug === slug);
}

export function findAssetCenterResource(
  domain: AssetCenterDomain,
  path: string,
): AssetCenterResource | undefined {
  return domain.resources.find((resource) => resource.path === path);
}

export function assetCenterHref(domain: AssetCenterDomain, resource: AssetCenterResource): string {
  return `/asset-center/${domain.slug}/${resource.path}`;
}

export function assetCenterCountKey(
  domain: AssetCenterDomain,
  resource: AssetCenterResource,
): string {
  return `${domain.slug}/${resource.path}`;
}

export function isPolicyResource(resource: AssetCenterResource): boolean {
  return resource.path === "industry-policies" || resource.path === "education-policies";
}
