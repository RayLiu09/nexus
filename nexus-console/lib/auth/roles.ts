export const CONSOLE_SESSION_ROLES = ["platform_data_admin", "business_expert"] as const;

export type SessionRole = (typeof CONSOLE_SESSION_ROLES)[number];

export const CONSOLE_ROLE_LABELS: Record<SessionRole, string> = {
  platform_data_admin: "平台数据管理员",
  business_expert: "业务专家",
};

export function isConsoleSessionRole(value: unknown): value is SessionRole {
  return (
    typeof value === "string" &&
    (CONSOLE_SESSION_ROLES as readonly string[]).includes(value)
  );
}
