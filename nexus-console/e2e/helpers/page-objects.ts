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
          {
            id: "ds-001",
            code: "ds_hr",
            name: "HR 系统",
            source_type: "record",
            status: "active",
            owner_user_id: null,
            org_scope_hint: [],
            default_governance_hints: {},
            connection_config: null,
            description: "HR 主数据",
            created_at: "2025-01-01T00:00:00Z",
            updated_at: "2025-01-01T00:00:00Z",
          },
          {
            id: "ds-002",
            code: "ds_doc",
            name: "文档库",
            source_type: "document",
            status: "active",
            owner_user_id: null,
            org_scope_hint: [],
            default_governance_hints: {},
            connection_config: null,
            description: null,
            created_at: "2025-01-01T00:00:00Z",
            updated_at: "2025-01-01T00:00:00Z",
          },
        ],
        meta: { trace_id: "e2e-001", total: 2 },
      },
    });
  });

  await page.route(`${API}/v1/jobs`, async (route) => {
    await route.fulfill({
      json: {
        data: [
          {
            id: "job-001",
            job_type: "pipeline_a",
            status: "running",
            ingest_batch_id: null,
            raw_object_id: "raw-001",
            retry_count: 0,
            current_stage: "document_parse",
            failure_reason: null,
            trace_id: null,
            metadata_summary: {},
            created_at: "2025-06-01T00:00:00Z",
            updated_at: "2025-06-01T00:00:00Z",
          },
          {
            id: "job-002",
            job_type: "pipeline_b",
            status: "succeeded",
            ingest_batch_id: null,
            raw_object_id: "raw-002",
            retry_count: 0,
            current_stage: "complete",
            failure_reason: null,
            trace_id: null,
            metadata_summary: {},
            created_at: "2025-06-01T00:00:00Z",
            updated_at: "2025-06-01T00:00:00Z",
          },
          {
            id: "job-003",
            job_type: "pipeline_a",
            status: "queued",
            ingest_batch_id: null,
            raw_object_id: "raw-003",
            retry_count: 0,
            current_stage: null,
            failure_reason: null,
            trace_id: null,
            metadata_summary: {},
            created_at: "2025-06-01T00:00:00Z",
            updated_at: "2025-06-01T00:00:00Z",
          },
          {
            id: "job-004",
            job_type: "pipeline_a",
            status: "failed",
            ingest_batch_id: null,
            raw_object_id: "raw-004",
            retry_count: 2,
            current_stage: "assetize",
            failure_reason: "checksum mismatch",
            trace_id: null,
            metadata_summary: {},
            created_at: "2025-06-01T00:00:00Z",
            updated_at: "2025-06-01T00:00:00Z",
          },
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
        data: {
          api: "healthy",
          database: "connected",
          workers: "2/4",
          queue: "0 pending",
          recent_error: null,
        },
        meta: { trace_id: "e2e-004" },
      },
    });
  });

  await page.route(`${API}/v1/assets/summary`, async (route) => {
    await route.fulfill({
      json: {
        data: { total: 120, validated: 98, pending: 15, failed: 7 },
        meta: { trace_id: "e2e-005" },
      },
    });
  });

  await page.route(`${API}/v1/raw-objects/summary`, async (route) => {
    await route.fulfill({
      json: {
        data: { total: 200, validated: 180, pending: 12, failed: 8 },
        meta: { trace_id: "e2e-006" },
      },
    });
  });

  // Fallback: empty array for any other API route
  await page.route(`${API}/**/*`, async (route) => {
    await route.fulfill({
      json: { data: [], meta: { trace_id: "e2e-fallback" } },
    });
  });
}

/**
 * Retrieval-test panel page object.
 *
 * The panel calls two console-side proxy routes:
 *   - `/api/knowledge-retrieval/plans` (Plan Only mode)
 *   - `/api/knowledge-retrieval`       (Full Run mode)
 *
 * We intercept both directly so tests never hit the backend (nexus-api)
 * and stay deterministic. See `mockRetrievalApi(page, ...)` below.
 */
export class RetrievalTestPage {
  readonly panel: Locator;
  readonly querySelect: Locator;
  readonly queryInput: Locator;
  readonly modeSwitch: Locator;
  readonly submitButton: Locator;
  readonly intentSlot: Locator;
  readonly planSlot: Locator;
  readonly resultsSlot: Locator;
  readonly warningsSlot: Locator;

  constructor(readonly page: Page) {
    this.panel = page.getByTestId("retrieval-test-panel");
    this.querySelect = page.getByTestId("fixture-select");
    this.queryInput = page.getByTestId("query-input");
    this.modeSwitch = page.getByTestId("mode-switch");
    this.submitButton = page.getByTestId("submit-button");
    this.intentSlot = page.getByTestId("intent-slot");
    this.planSlot = page.getByTestId("plan-slot");
    this.resultsSlot = page.getByTestId("results-slot");
    this.warningsSlot = page.getByTestId("warnings-slot");
  }

  async goto() {
    // Pretend we're authenticated so the middleware doesn't redirect
    // to /login. The backend proxy calls are all intercepted below,
    // so the token value itself is never validated.
    await this.page.context().addCookies([
      {
        name: "nexus_access_token",
        value: "e2e-fake-token",
        domain: "localhost",
        path: "/",
      },
    ]);
    await this.page.goto("/retrieval-test");
  }

  async submitFreeform(query: string) {
    await this.queryInput.fill(query);
    await this.submitButton.click();
  }

  async submitPreset(presetLabel: string | RegExp) {
    await this.querySelect.click();
    // Antd Select dropdown renders options in a portal; select by role.
    await this.page.getByRole("option", { name: presetLabel }).click();
    await this.submitButton.click();
  }

  async switchMode(mode: "Plan Only" | "Full Run") {
    await this.modeSwitch.getByText(mode).click();
  }
}

/**
 * Sample KnowledgeRetrievalResponse used by mockRetrievalApi. Kept
 * intentionally small — the panel only needs enough fields to render
 * intent + plan + one result + one warning.
 */
export function makeRetrievalResponse(
  overrides: {
    status?: string;
    hasPlan?: boolean;
    hasResults?: boolean;
    warnings?: string[];
  } = {},
): unknown {
  const { status = "completed", hasPlan = true, hasResults = true, warnings = [] } = overrides;
  return {
    query_id: "qr-e2e-001",
    status,
    original_query: "北京的电商运营岗位",
    intent: {
      business_domains: ["job_demand"],
      retrieval_channels: ["structured"],
      question_type: "list",
      output_expectation: ["records"],
      constraints: { regions: ["北京"] },
      confidence: 0.82,
      confidence_threshold: 0.7,
      candidate_intents: [],
      missing_constraints: [],
      suggested_refinements: [],
    },
    retrieval_plan: hasPlan
      ? {
          original_query: "北京的电商运营岗位",
          sub_queries: [
            {
              query_id: "q1",
              channel: "structured",
              domain: "job_demand",
              purpose: "regions_narrow",
              query_text: "北京岗位",
              structured_plan: {
                table_profile: "job_demand.v1",
                query_profile: "job_demand.record_list",
              },
              unstructured_plan: null,
            },
          ],
          merge_goal: "regions tag_filter 收窄",
        }
      : null,
    retrieval_results: hasResults
      ? [
          {
            query_id: "q1",
            channel: "structured",
            domain: "job_demand",
            status: "completed",
            result_shape: "record_list",
            records: [{ id: "record-jd-bj", city: "北京" }],
            items: [],
            aggregations: [],
            source_refs: [],
            elapsed_ms: 42.5,
            error_message: null,
          },
        ]
      : [],
    llm_summary: null,
    markdown: null,
    access_scope: "all_assets",
    conversation_steps: [
      {
        step: "intent_recognition",
        status: "completed",
        title: "意图识别",
        display_to_user: true,
        message: "识别为 job_demand 领域",
        display_payload: {},
      },
    ],
    source_refs: [],
    clarification: null,
    warnings,
  };
}

/**
 * Intercept the two console-side proxy routes with fixed envelopes.
 * `mode` controls which endpoint responds successfully; the other is
 * left untouched. `errorEndpoint` overrides one endpoint with a 500.
 */
export async function mockRetrievalApi(
  page: Page,
  opts: {
    planResponse?: unknown;
    fullResponse?: unknown;
    errorEndpoint?: "plans" | "full";
  } = {},
) {
  const planResponse = opts.planResponse ?? makeRetrievalResponse({ hasResults: false });
  const fullResponse = opts.fullResponse ?? makeRetrievalResponse();

  await page.route("**/api/knowledge-retrieval/plans", async (route) => {
    if (opts.errorEndpoint === "plans") {
      await route.fulfill({
        status: 500,
        json: { ok: false, status: 500, message: "e2e mock: plans failure" },
      });
      return;
    }
    await route.fulfill({
      json: { ok: true, status: 200, data: planResponse, traceId: "e2e-plan-001" },
    });
  });

  await page.route("**/api/knowledge-retrieval", async (route) => {
    if (opts.errorEndpoint === "full") {
      await route.fulfill({
        status: 500,
        json: { ok: false, status: 500, message: "e2e mock: full failure" },
      });
      return;
    }
    await route.fulfill({
      json: { ok: true, status: 200, data: fullResponse, traceId: "e2e-full-001" },
    });
  });
}
