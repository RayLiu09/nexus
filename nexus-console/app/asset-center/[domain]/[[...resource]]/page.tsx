import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import {
  type AbilityAnalysis,
  getApiData,
  type MajorDistributionRecord,
  type TeachingStandardCourse,
  type TeachingStandardLibrary,
} from "@/lib/api";
import { findAssetCenterDomain, findAssetCenterResource } from "@/lib/asset-center/catalog";
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
  const pagination = parsePaginationParams(query);
  const page = pagination.page ?? 1;
  const pageSize = pagination.pageSize ?? DEFAULT_PAGE_SIZE;

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

  if (domain.slug === "major" && resource.path === "distributions") {
    const filters: MajorDistributionFilters = {
      year: first(query.year),
      province_name: first(query.province_name),
      major_name: first(query.major_name),
      major_code: first(query.major_code),
      education_level: first(query.education_level),
      region_scope: first(query.region_scope),
    };
    const result = await getApiData<MajorDistributionRecord[]>(
      "/internal/v1/record-assets/major-distribution-records",
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
