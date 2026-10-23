export type DocumentTagFilters = {
  region?: string;
  industry?: string;
  content_tag?: string;
};

export type DocumentIdentityFilters = {
  major_name?: string;
  major_code?: string;
  institution_name?: string;
};

export type ReportDocumentFilters = DocumentIdentityFilters & { content_tag?: string };

const IDENTITY_FIELDS = ["major_name", "major_code", "institution_name"] as const;

export function documentIdentityFilters(
  query: Record<string, string | string[] | undefined>,
): DocumentIdentityFilters {
  return Object.fromEntries(
    IDENTITY_FIELDS.flatMap((field) => {
      const raw = query[field];
      const value = (Array.isArray(raw) ? raw[0] : raw)?.trim();
      return value ? [[field, value]] : [];
    }),
  );
}

export function documentIdentityQuery(filters: DocumentIdentityFilters): Record<string, string> {
  return Object.fromEntries(
    IDENTITY_FIELDS.flatMap((field) => {
      const value = filters[field]?.trim();
      return value ? [[field, value]] : [];
    }),
  );
}

export function reportDocumentQuery(filters: ReportDocumentFilters): Record<string, string> {
  return {
    ...documentIdentityQuery(filters),
    ...(filters.content_tag?.trim() ? { content_tag: filters.content_tag.trim() } : {}),
  };
}

const FIELDS = ["region", "industry", "content_tag"] as const;

export function documentTagFilters(
  query: Record<string, string | string[] | undefined>,
): DocumentTagFilters {
  const result: DocumentTagFilters = {};
  for (const field of FIELDS) {
    const raw = query[field];
    const value = (Array.isArray(raw) ? raw[0] : raw)?.trim();
    if (value) result[field] = value;
  }
  return result;
}

export function documentTagQuery(filters: DocumentTagFilters): Record<string, string> {
  return Object.fromEntries(
    FIELDS.flatMap((field) => {
      const value = filters[field]?.trim();
      return value ? [[field, value]] : [];
    }),
  );
}
