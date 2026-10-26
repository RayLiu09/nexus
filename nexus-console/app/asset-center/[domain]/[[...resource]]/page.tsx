import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import {
  type AbilityAnalysis,
  type CourseTextbookSummary,
  getApiData,
  type MajorOfferingRecord,
  type OccupationDictionaryRecord,
  type MajorProfileDocument,
  type IndustryPolicy,
  type RawJob,
  type IndustrialPark,
  type Enterprise,
  type TalentTrainingPlanSummary,
  type TalentDemandReport,
  type TeachingCase,
  type TeachingStandardCourse,
  type TeachingStandardLibrary,
} from "@/lib/api";
import { findAssetCenterDomain, findAssetCenterResource } from "@/lib/asset-center/catalog";
import {
  documentIdentityFilters,
  documentIdentityQuery,
  reportDocumentQuery,
  documentTagFilters,
  documentTagQuery,
} from "@/lib/asset-center/document-filters";
import { getServerSession } from "@/lib/auth/serverSession";
import { DEFAULT_PAGE_SIZE, parsePaginationParams } from "@/lib/pagination";
import { normalizePolicyLevel } from "../../_components/PolicyLevelNav";
import { ResourceShell } from "../../_components/ResourceShell";
import {
  TeachingStandardsTable,
  type TeachingStandardFilters,
} from "../../_components/TeachingStandardsTable";
import {
  StandardCourseLibraryTable,
  type StandardCourseFilters,
} from "../../_components/StandardCourseLibraryTable";
import {
  MajorDistributionTable,
  type MajorDistributionFilters,
} from "../../_components/MajorDistributionTable";
import {
  OccupationalAnalysisTable,
  type OccupationalAnalysisFilters,
} from "../../_components/OccupationalAnalysisTable";
import {
  TalentTrainingPlansTable,
  type TalentTrainingPlanFilters,
} from "../../_components/TalentTrainingPlansTable";
import {
  CourseTextbooksTable,
  type CourseTextbookFilters,
} from "../../_components/CourseTextbooksTable";
import { MajorProfilesTable, type MajorProfileFilters } from "../../_components/MajorProfilesTable";
import { IndustryPoliciesTable } from "../../_components/IndustryPoliciesTable";
import { TalentDemandReportsTable } from "../../_components/TalentDemandReportsTable";
import { TeachingCasesTable } from "../../_components/TeachingCasesTable";
import { JobDemandTable, type JobDemandFilters } from "../../_components/JobDemandTable";
import { IndustrialParksTable } from "../../_components/IndustrialParksTable";
import { EnterprisesTable } from "../../_components/EnterprisesTable";

import {
  OccupationDictionaryTable,
  type OccupationDictionaryFilters,
} from "../../_components/OccupationDictionaryTable";

type AssetCenterRouteProps = {
  params: Promise<{ domain: string; resource?: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AssetCenterRoute({ params, searchParams }: AssetCenterRouteProps) {
  const route = await params;
  const domain = findAssetCenterDomain(route.domain);
  if (!domain) notFound();

  const resourcePath = route.resource?.join("/");
  if (!resourcePath) notFound();

  const resource = findAssetCenterResource(domain, resourcePath);
  if (!resource) notFound();

  const query = await searchParams;
  const tagFilters = documentTagFilters(query);
  const tagQuery = documentTagQuery(tagFilters);
  const pagination = parsePaginationParams(query);
  const page = pagination.page ?? 1;
  const pageSize = pagination.pageSize ?? DEFAULT_PAGE_SIZE;

  if (domain.slug === "teaching-resources" && resource.path === "cases") {
    const result = await getApiData<TeachingCase[]>("/internal/v1/teaching-cases", [], {
      page: String(page),
      pageSize: String(pageSize),
      ...tagQuery,
    });
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <TeachingCasesTable
          filters={tagFilters}
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "talent-demand-reports") {
    const filters = {
      ...documentIdentityFilters(query),
      ...(tagFilters.content_tag ? { content_tag: tagFilters.content_tag } : {}),
    };
    const session = await getServerSession();
    const result = await getApiData<TalentDemandReport[]>(
      "/internal/v1/talent-demand-reports",
      [],
      { page: String(page), pageSize: String(pageSize), ...reportDocumentQuery(filters) },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <TalentDemandReportsTable
          filters={filters}
          canEdit={session?.role === "business_expert"}
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "profiles") {
    const session = await getServerSession();
    const filters: MajorProfileFilters = documentIdentityFilters(query);
    const result = await getApiData<MajorProfileDocument[]>(
      "/internal/v1/major-profile-documents",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        ...documentIdentityQuery(filters),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <MajorProfilesTable
          canEdit={session?.role === "business_expert" || session?.role === "platform_data_admin"}
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (
    domain.slug === "policy" &&
    ["industry-policies", "industry-reports", "sector-reports"].includes(resource.path)
  ) {
    const topicValue = first(query.topic);
    const topic =
      topicValue === "finance_commerce" || topicValue === "low_altitude" ? topicValue : undefined;
    const endpoint = `/internal/v1/${resource.path}`;
    const [result, allResult, financeResult, lowAltitudeResult] = await Promise.all([
      getApiData<IndustryPolicy[]>(endpoint, [], {
        page: String(page),
        pageSize: String(pageSize),
        ...tagQuery,
        ...(topic ? { topic } : {}),
      }),
      topic
        ? getApiData<IndustryPolicy[]>(endpoint, [], { page: "1", pageSize: "1", ...tagQuery })
        : null,
      getApiData<IndustryPolicy[]>(endpoint, [], {
        page: "1",
        pageSize: "1",
        ...tagQuery,
        topic: "finance_commerce",
      }),
      getApiData<IndustryPolicy[]>(endpoint, [], {
        page: "1",
        pageSize: "1",
        ...tagQuery,
        topic: "low_altitude",
      }),
    ]);
    const isReport = resource.path !== "industry-policies";
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <IndustryPoliciesTable
          filters={tagFilters}
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
          topic={topic}
          allCount={(allResult ?? result).ok ? ((allResult ?? result).total ?? 0) : null}
          topicCounts={{
            finance_commerce: financeResult.ok ? (financeResult.total ?? 0) : null,
            low_altitude: lowAltitudeResult.ok ? (lowAltitudeResult.total ?? 0) : null,
          }}
          showRegion={!isReport}
          emptyText={`暂无${resource.name}`}
          nameColumnTitle={isReport ? "报告名称" : "资产名称"}
        />
      </div>
    );
  }

  if (domain.slug === "market" && resource.path === "job-demands") {
    const filters: JobDemandFilters = {
      q: first(query.q),
      industry: first(query.industry),
    };
    const result = await getApiData<RawJob[]>("/internal/v1/raw-jobs", [], {
      page: String(page),
      pageSize: String(pageSize),
      ...Object.fromEntries(
        Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
      ),
    });
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <JobDemandTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "market" && resource.path === "industrial-parks") {
    const q = first(query.q);
    const industry = first(query.industry);
    const result = await getApiData<IndustrialPark[]>("/internal/v1/industrial-parks", [], {
      page: String(page),
      pageSize: String(pageSize),
      ...(q ? { q } : {}),
      ...(industry ? { industry } : {}),
    });
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <IndustrialParksTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          q={q}
          industry={industry}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "market" && resource.path === "enterprises") {
    const q = first(query.q);
    const result = await getApiData<Enterprise[]>("/internal/v1/enterprises", [], {
      page: String(page),
      pageSize: String(pageSize),
      ...(q ? { q } : {}),
    });
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <EnterprisesTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          q={q}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "teaching-resources" && resource.path === "course-textbooks") {
    const yearValue = first(query.publication_year);
    const parsedYear = yearValue ? Number.parseInt(yearValue, 10) : undefined;
    const filters: CourseTextbookFilters = {
      title: first(query.title),
      textbook_type: first(query.textbook_type) as CourseTextbookFilters["textbook_type"],
      publisher: first(query.publisher),
      chief_editor: first(query.chief_editor),
      publication_year: Number.isFinite(parsedYear) ? parsedYear : undefined,
    };
    const result = await getApiData<CourseTextbookSummary[]>("/internal/v1/course-textbooks", [], {
      page: String(page),
      pageSize: String(pageSize),
      ...Object.fromEntries(
        Object.entries(filters)
          .filter((entry) => entry[1] !== undefined && entry[1] !== "")
          .map(([key, value]) => [key, String(value)]),
      ),
    });
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <CourseTextbooksTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "occupation-analyses") {
    const filters: OccupationalAnalysisFilters = {
      major_name: first(query.major_name),
    };
    const result = await getApiData<AbilityAnalysis[]>(
      "/internal/v1/record-assets/ability-analyses",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        ...(filters.major_name ? { major_name: filters.major_name } : {}),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader eyebrow={domain.name} title="职业能力分析" description={resource.description} />
        <OccupationalAnalysisTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "occupation-dictionary") {
    const filters: OccupationDictionaryFilters = {
      major_group: first(query.major_group)?.trim() || undefined,
      minor_group: first(query.minor_group)?.trim() || undefined,
      occupation_name: first(query.occupation_name)?.trim() || undefined,
    };
    const result = await getApiData<OccupationDictionaryRecord[]>(
      "/internal/v1/occupation-dictionary",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        ...Object.fromEntries(
          Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
        ),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <OccupationDictionaryTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "distributions") {
    const session = await getServerSession();
    const filters: MajorDistributionFilters = {
      year: first(query.year),
      province_name: first(query.province_name),
      major_name: first(query.major_name),
      major_code: first(query.major_code),
      school_name: first(query.school_name),
    };
    const result = await getApiData<MajorOfferingRecord[]>(
      "/internal/v1/major-offerings",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        ...Object.fromEntries(
          Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
        ),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <MajorDistributionTable
          canImport={session?.role === "business_expert" || session?.role === "platform_data_admin"}
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "training-plans") {
    const filters: TalentTrainingPlanFilters = {
      major_name: first(query.major_name),
      major_code: first(query.major_code),
      institution_name: first(query.institution_name),
      education_level: first(query.education_level),
    };
    const result = await getApiData<TalentTrainingPlanSummary[]>(
      "/internal/v1/talent-training-plans",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        official_only: "true",
        catalog_visible_only: "true",
        ...Object.fromEntries(
          Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
        ),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <TalentTrainingPlansTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "teaching-standards") {
    const filters: TeachingStandardFilters = {
      major_code: first(query.major_code),
      major_name: first(query.major_name),
      education_level: first(query.education_level),
      status: first(query.status),
    };
    const result = await getApiData<TeachingStandardLibrary[]>(
      "/internal/v1/teaching-standard-libraries",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        ...Object.fromEntries(
          Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
        ),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
        />
        <TeachingStandardsTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  if (domain.slug === "major" && resource.path === "standard-course-library") {
    const filters: StandardCourseFilters = {
      libraryId: first(query.libraryId),
      course_name: first(query.course_name),
      major_code: first(query.major_code),
      major_name: first(query.major_name),
      education_level: first(query.education_level),
      course_type: first(query.course_type),
    };
    const backendFilters = {
      library_id: filters.libraryId,
      course_name: filters.course_name,
      major_code: filters.major_code,
      major_name: filters.major_name,
      education_level: filters.education_level,
      course_type: filters.course_type,
    };
    const result = await getApiData<TeachingStandardCourse[]>(
      "/internal/v1/teaching-standard-courses",
      [],
      {
        page: String(page),
        pageSize: String(pageSize),
        ...Object.fromEntries(
          Object.entries(backendFilters).filter((entry): entry is [string, string] =>
            Boolean(entry[1]),
          ),
        ),
      },
    );
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow={domain.name}
          title={resource.name}
          description={resource.description}
          actions={
            <Link
              href="/asset-center/major/teaching-standards"
              className="text-accent inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
            >
              <ArrowLeft size={16} aria-hidden="true" />
              返回专业标准库
            </Link>
          }
        />
        <StandardCourseLibraryTable
          rows={result.data}
          total={result.total ?? result.data.length}
          page={page}
          pageSize={pageSize}
          filters={filters}
          ok={result.ok}
          error={result.error}
          traceId={result.traceId}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow={domain.name} title={resource.name} description={resource.description} />
      <ResourceShell
        domain={domain}
        resource={resource}
        policyLevel={normalizePolicyLevel(query.policyLevel)}
      />
    </div>
  );
}
