import { apiBaseUrl } from "./api";

export interface PromptTemplateSummary {
  id: string;
  task_type: string;
  template_name: string;
  template_version: number;
  status: string;
  litellm_model_alias: string | null;
  temperature: number | null;
  max_input_tokens: number | null;
  redaction_policy: Record<string, unknown> | null;
  change_summary: string | null;
  created_at: string | null;
  created_by: string | null;
}

export interface PromptTemplateDetail extends PromptTemplateSummary {
  prompt_template: string;
  output_schema_version: string | null;
  updated_at: string | null;
}

export interface UpdatePromptTemplatePayload {
  template_name?: string;
  prompt_template?: string;
  output_schema_version?: string | null;
  litellm_model_alias?: string | null;
  temperature?: number | null;
  max_input_tokens?: number | null;
  redaction_policy?: Record<string, unknown> | null;
  change_summary?: string;
}

const BASE = `${apiBaseUrl()}/api/admin/governance-prompts`;

export async function fetchPromptTemplates(): Promise<{
  ok: true;
  templates: PromptTemplateSummary[];
} | {
  ok: false;
  error: string;
}> {
  try {
    const res = await fetch(BASE, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const json = await res.json();
    return { ok: true, templates: json.data as PromptTemplateSummary[] };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function fetchPromptTemplate(
  templateId: string,
): Promise<{
  ok: true;
  template: PromptTemplateDetail;
} | {
  ok: false;
  error: string;
}> {
  try {
    const res = await fetch(`${BASE}/${templateId}`, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const json = await res.json();
    return { ok: true, template: json.data as PromptTemplateDetail };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updatePromptTemplate(
  taskType: string,
  payload: UpdatePromptTemplatePayload,
): Promise<{
  ok: true;
  template: PromptTemplateSummary;
} | {
  ok: false;
  status: number;
  error: string;
}> {
  try {
    const res = await fetch(`${BASE}/${taskType}/active`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const json = await res.json();
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error: json?.detail ?? `HTTP ${res.status}`,
      };
    }
    return { ok: true, template: json.data as PromptTemplateSummary };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

export async function disablePromptTemplate(
  templateId: string,
): Promise<{
  ok: true;
} | {
  ok: false;
  error: string;
}> {
  try {
    const res = await fetch(`${BASE}/${templateId}/disable`, {
      method: "POST",
      cache: "no-store",
    });
    if (!res.ok) {
      const json = await res.json().catch(() => null);
      return { ok: false, error: json?.detail ?? `HTTP ${res.status}` };
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
