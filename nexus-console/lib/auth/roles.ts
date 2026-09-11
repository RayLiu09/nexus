export const CONSOLE_SESSION_ROLES = ["platform_data_admin", "business_expert"] as const;

export type SessionRole = (typeof CONSOLE_SESSION_ROLES)[number];

export const CONSOLE_ROLE_LABELS: Record<SessionRole, string> = {
  platform_data_admin: "平台数据管理员",
  business_expert: "业务专家",
};

/** Short (Tag-friendly) role labels for tables and badges. */
export const CONSOLE_ROLE_SHORT_LABELS: Record<SessionRole, string> = {
  platform_data_admin: "数据管理员",
  business_expert: "业务专家",
};

/** Default avatar SVG served from `public/avatars/*.svg`. */
export const CONSOLE_ROLE_AVATARS: Record<SessionRole, string> = {
  platform_data_admin: "/avatars/data-admin.svg",
  business_expert: "/avatars/business-expert.svg",
};

/** Landing route each role should see after login / root redirect. */
export const CONSOLE_ROLE_HOME: Record<SessionRole, string> = {
  platform_data_admin: "/workbench",
  business_expert: "/asset-center",
};

export function isConsoleSessionRole(value: unknown): value is SessionRole {
  return (
    typeof value === "string" &&
    (CONSOLE_SESSION_ROLES as readonly string[]).includes(value)
  );
}
