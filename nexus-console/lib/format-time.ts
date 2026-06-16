/**
 * 时间格式化（A7 时间统一规则）
 *
 * 规则：
 *   - ≤ 60 秒        → "刚刚"
 *   - ≤ 60 分钟      → "N 分钟前"
 *   - 同一自然日      → "今日 HH:mm"
 *   - 昨日           → "昨日 HH:mm"
 *   - 7 天内         → "N 天前"
 *   - 跨年外         → "YYYY-MM-DD HH:mm"
 *   - 同年外         → "MM-DD HH:mm"
 *
 * tooltip / aria-label 一律返回 ISO 字符串，便于读屏与 hover 显示。
 */

export interface FormattedTime {
  /** 渲染在文本节点 */
  display: string;
  /** 用作 title / aria-label / tooltip */
  iso: string;
}

function isValidDate(d: Date): boolean {
  return Number.isFinite(d.getTime());
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function formatTime(input: string | number | Date | null | undefined, now: Date = new Date()): FormattedTime {
  if (input === null || input === undefined || input === "") {
    return { display: "-", iso: "" };
  }
  const d = input instanceof Date ? input : new Date(input);
  if (!isValidDate(d)) {
    return { display: "-", iso: "" };
  }
  const iso = d.toISOString();
  const diffMs = now.getTime() - d.getTime();
  const diffSec = Math.round(diffMs / 1000);
  const diffMin = Math.round(diffSec / 60);

  if (diffSec >= 0 && diffSec < 60) return { display: "刚刚", iso };
  if (diffMin >= 0 && diffMin < 60) return { display: `${diffMin} 分钟前`, iso };

  const hhmm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;

  if (sameDay(d, now)) return { display: `今日 ${hhmm}`, iso };

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, yesterday)) return { display: `昨日 ${hhmm}`, iso };

  const diffDay = Math.floor(diffMs / 86_400_000);
  if (diffDay > 0 && diffDay < 7) return { display: `${diffDay} 天前`, iso };

  const yyyy = d.getFullYear();
  const mm = pad2(d.getMonth() + 1);
  const dd = pad2(d.getDate());

  if (yyyy === now.getFullYear()) return { display: `${mm}-${dd} ${hhmm}`, iso };
  return { display: `${yyyy}-${mm}-${dd} ${hhmm}`, iso };
}

/**
 * SLA 倒计时分层（与 governance review-card 的 priority-overdue / priority-today 对应）
 */
export type SlaTier = "overdue" | "today" | "normal";

export function slaTier(deadline: string | number | Date | null | undefined, now: Date = new Date()): SlaTier {
  if (deadline === null || deadline === undefined || deadline === "") return "normal";
  const d = deadline instanceof Date ? deadline : new Date(deadline);
  if (!isValidDate(d)) return "normal";
  const diffMs = d.getTime() - now.getTime();
  if (diffMs < 0) return "overdue";
  if (diffMs < 24 * 3600 * 1000) return "today";
  return "normal";
}

export function formatSla(deadline: string | number | Date | null | undefined, now: Date = new Date()): string {
  if (deadline === null || deadline === undefined || deadline === "") return "-";
  const d = deadline instanceof Date ? deadline : new Date(deadline);
  if (!isValidDate(d)) return "-";
  const diffMs = d.getTime() - now.getTime();
  const abs = Math.abs(diffMs);
  const hours = Math.floor(abs / 3600_000);
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;

  if (diffMs < 0) {
    if (days > 0) return `超时 ${days}d ${remHours}h`;
    return `超时 ${hours}h`;
  }
  if (hours < 24) return `剩余 ${hours}h`;
  return `剩余 ${days}d ${remHours}h`;
}
