import type { Page, Locator } from "@playwright/test";

/**
 * Login page object.
 */
export class LoginPage {
  readonly username: Locator;
  readonly password: Locator;
  readonly submit: Locator;

  constructor(readonly page: Page) {
    this.username = page.getByPlaceholder(/用户名/);
    this.password = page.getByPlaceholder(/密码/);
    this.submit = page.getByRole("button", { name: /登录/ });
  }

  async goto() {
    await this.page.goto("/login");
  }

  async login(username: string, password: string) {
    await this.username.fill(username);
    await this.password.fill(password);
    await this.submit.click();
  }
}

/**
 * Workbench (dashboard) page object.
 */
export class WorkbenchPage {
  readonly heading: Locator;

  constructor(readonly page: Page) {
    this.heading = page.getByRole("heading", { level: 1 });
  }

  async goto() {
    await this.page.goto("/workbench");
  }
}

/**
 * Data sources list page object.
 */
export class DataSourcesPage {
  readonly heading: Locator;
  readonly newButton: Locator;

  constructor(readonly page: Page) {
    this.heading = page.getByRole("heading", { level: 1 });
    this.newButton = page.getByRole("button", { name: /新建|新增|创建/ });
  }

  async goto() {
    await this.page.goto("/data-sources");
  }
}

/**
 * Jobs center page object.
 */
export class JobsPage {
  readonly heading: Locator;

  constructor(readonly page: Page) {
    this.heading = page.getByRole("heading", { level: 1 });
  }

  async goto() {
    await this.page.goto("/jobs");
  }
}

/**
 * Mock common API routes with JSON responses.
 * Returns an array of route handlers for cleanup.
 */
export async function mockApi(page: Page) {
  const API = "http://127.0.0.1:8000";

  await page.route(`${API}/v1/data-sources`, async (route) => {
    await route.fulfill({
      json: {
        data: [
          { id: "ds-001", code: "ds_hr", name: "HR 系统", source_type: "record", status: "active", owner_user_id: null, org_scope_hint: [], default_governance_hints: {}, connection_config: null, description: "HR 主数据", created_at: "2025-01-01T00:00:00Z", updated_at: "2025-01-01T00:00:00Z" },
          { id: "ds-002", code: "ds_doc", name: "文档库", source_type: "document", status: "active", owner_user_id: null, org_scope_hint: [], default_governance_hints: {}, connection_config: null, description: null, created_at: "2025-01-01T00:00:00Z", updated_at: "2025-01-01T00:00:00Z" },
        ],
        meta: { trace_id: "e2e-001", total: 2 },
      },
    });
  });

  await page.route(`${API}/v1/jobs`, async (route) => {
    await route.fulfill({
      json: {
        data: [
          { id: "job-001", job_type: "pipeline_a", status: "running", ingest_batch_id: null, raw_object_id: "raw-001", retry_count: 0, current_stage: "document_parse", failure_reason: null, trace_id: null, metadata_summary: {}, created_at: "2025-06-01T00:00:00Z", updated_at: "2025-06-01T00:00:00Z" },
          { id: "job-002", job_type: "pipeline_b", status: "succeeded", ingest_batch_id: null, raw_object_id: "raw-002", retry_count: 0, current_stage: "complete", failure_reason: null, trace_id: null, metadata_summary: {}, created_at: "2025-06-01T00:00:00Z", updated_at: "2025-06-01T00:00:00Z" },
          { id: "job-003", job_type: "pipeline_a", status: "queued", ingest_batch_id: null, raw_object_id: "raw-003", retry_count: 0, current_stage: null, failure_reason: null, trace_id: null, metadata_summary: {}, created_at: "2025-06-01T00:00:00Z", updated_at: "2025-06-01T00:00:00Z" },
          { id: "job-004", job_type: "pipeline_a", status: "failed", ingest_batch_id: null, raw_object_id: "raw-004", retry_count: 2, current_stage: "assetize", failure_reason: "checksum mismatch", trace_id: null, metadata_summary: {}, created_at: "2025-06-01T00:00:00Z", updated_at: "2025-06-01T00:00:00Z" },
        ],
        meta: { trace_id: "e2e-002", total: 4 },
      },
    });
  });

  await page.route(`${API}/v1/jobs/*/stages`, async (route) => {
    await route.fulfill({
      json: {
        data: [],
        meta: { trace_id: "e2e-003" },
      },
    });
  });

  await page.route(`${API}/v1/runtime/health`, async (route) => {
    await route.fulfill({
      json: {
        data: { api: "healthy", database: "connected", workers: "2/4", queue: "0 pending", recent_error: null },
        meta: { trace_id: "e2e-004" },
      },
    });
  });

  await page.route(`${API}/v1/assets/summary`, async (route) => {
    await route.fulfill({
      json: { data: { total: 120, validated: 98, pending: 15, failed: 7 }, meta: { trace_id: "e2e-005" } },
    });
  });

  await page.route(`${API}/v1/raw-objects/summary`, async (route) => {
    await route.fulfill({
      json: { data: { total: 200, validated: 180, pending: 12, failed: 8 }, meta: { trace_id: "e2e-006" } },
    });
  });

  // Fallback: empty array for any other API route
  await page.route(`${API}/**/*`, async (route) => {
    await route.fulfill({
      json: { data: [], meta: { trace_id: "e2e-fallback" } },
    });
  });
}
