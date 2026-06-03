/**
 * Dev-mode session helpers.
 *
 * 本周只做"开发态假登录"：用户在 /login 页选一个 mock 角色，session 写入
 * cookie（可被服务端 RSC 读取）+ localStorage（客户端容错）。等后端真正
 * 引入 IAM 时，只需替换 `setSession` / `clearSession` / `useSession`
 * 三个入口，业务代码不动。
 *
 * 注意：cookie 不设 httpOnly（需要客户端可读以做 redirect / Topbar 显示），
 * 也不签名 —— 这是 dev 模式的边界，真 IAM 上线时要严格收口。
 */
export type SessionRole = "platform_admin" | "data_steward" | "reviewer" | "reader";

export interface SessionOrg {
  id: string;
  name: string;
}

export interface Session {
  id: string;
  username: string;
  displayName: string;
  role: SessionRole;
  orgUnit: SessionOrg;
  env: "demo" | "staging" | "prod";
  /** 创建时间（epoch ms），用于 UI 显示登录时长。 */
  loggedInAt: number;
}

export const SESSION_COOKIE = "nexus_session";
export const SESSION_STORAGE_KEY = "nexus.session";

/** 7 天有效期；dev 模式无需 refresh token 概念。 */
const COOKIE_MAX_AGE_S = 60 * 60 * 24 * 7;

function isSession(value: unknown): value is Session {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.username === "string" &&
    typeof v.displayName === "string" &&
    typeof v.role === "string" &&
    typeof v.env === "string" &&
    typeof v.orgUnit === "object" &&
    v.orgUnit !== null
  );
}

export function encodeSession(s: Session): string {
  return encodeURIComponent(JSON.stringify(s));
}

export function decodeSession(raw: string | null | undefined): Session | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    return isSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** 客户端读 session（cookie 优先；localStorage 回填）。 */
export function getClientSession(): Session | null {
  if (typeof document === "undefined") return null;
  const cookie = readCookie(SESSION_COOKIE);
  const fromCookie = decodeSession(cookie);
  if (fromCookie) return fromCookie;
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    return decodeSession(raw);
  } catch {
    return null;
  }
}

/** 客户端写 session（cookie + localStorage 双写）。 */
export function setClientSession(s: Session): void {
  if (typeof document === "undefined") return;
  writeCookie(SESSION_COOKIE, encodeSession(s), COOKIE_MAX_AGE_S);
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, encodeSession(s));
  } catch {
    /* localStorage 可能被禁；忽略 */
  }
}

export function clearClientSession(): void {
  if (typeof document === "undefined") return;
  writeCookie(SESSION_COOKIE, "", 0);
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

function readCookie(name: string): string | null {
  const all = document.cookie.split(";");
  for (const part of all) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const key = part.slice(0, idx).trim();
    if (key === name) return part.slice(idx + 1).trim();
  }
  return null;
}

function writeCookie(name: string, value: string, maxAgeS: number): void {
  const parts = [`${name}=${value}`, "path=/", `max-age=${maxAgeS}`, "samesite=lax"];
  if (typeof location !== "undefined" && location.protocol === "https:") {
    parts.push("secure");
  }
  document.cookie = parts.join("; ");
}
