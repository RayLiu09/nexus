/**
 * Shared pagination types and helpers.
 *
 * Convention:
 * - Server components read `page`/`pageSize` from Next.js searchParams.
 * - getApiData passes them as query string to the backend.
 * - Backend returns `PaginatedResponse<T>` with `items` + `total`.
 * - Antd Table `pagination` drives URL updates via router.replace().
 */

/** Query parameters sent to backend for paginated endpoints. */
export interface PaginationParams {
  page?: number;
  pageSize?: number;
}

/** Standard backend paginated response envelope. */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

/** Default page size used across all paginated tables. */
export const DEFAULT_PAGE_SIZE = 20;

/** Parse page and pageSize from Next.js searchParams (which may be string | string[] | undefined). */
export function parsePaginationParams(
  searchParams: Record<string, string | string[] | undefined>,
): PaginationParams {
  const rawPage = searchParams.page;
  const rawPageSize = searchParams.pageSize;

  const pageStr = Array.isArray(rawPage) ? rawPage[0] : rawPage;
  const sizeStr = Array.isArray(rawPageSize) ? rawPageSize[0] : rawPageSize;

  const page = pageStr ? parseInt(pageStr, 10) : undefined;
  const pageSize = sizeStr ? parseInt(sizeStr, 10) : undefined;

  const result: PaginationParams = {};
  if (page && page > 0) result.page = page;
  if (pageSize && pageSize > 0 && pageSize <= 100) result.pageSize = pageSize;
  return result;
}

/** Build a query string from PaginationParams (e.g., "page=2&pageSize=20"). */
export function toQueryString(params: PaginationParams): string {
  const parts: string[] = [];
  if (params.page) parts.push(`page=${params.page}`);
  if (params.pageSize) parts.push(`pageSize=${params.pageSize}`);
  return parts.join("&");
}
