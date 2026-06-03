/**
 * 服务端读 session（RSC / route handler 入口）。
 *
 * 与 `lib/auth/session.ts` 配对：客户端写 cookie，服务端通过
 * `next/headers` 的 `cookies()` 读出来。仅供 server components 使用。
 */
import { cookies } from "next/headers";

import { SESSION_COOKIE, decodeSession, type Session } from "./session";

export async function getServerSession(): Promise<Session | null> {
  const store = await cookies();
  const raw = store.get(SESSION_COOKIE)?.value;
  return decodeSession(raw ?? null);
}
