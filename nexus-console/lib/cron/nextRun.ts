/**
 * 极简 cron next-firing 计算器
 *
 * 支持我们 CronPicker 生成的预设形态：每字段只接受 `*` 或单个整数。
 * 任何更复杂的语法（列表 `1,2`、范围 `1-5`、步长 `&#42;/5`、月/日特殊值等）
 * 一律返回 null，由调用方降级展示原始 cron。
 *
 * 设计取舍：避免引入 cron-parser 这类有 ESM/CJS 互操作历史问题的依赖。
 * 后续如果需要支持复杂表达式，再单独评估。
 */

const MAX = {
  minute: 59,
  hour: 23,
  dom: 31,
  month: 12,
  dow: 6,
} as const;

type ParsedField = "*" | number;

function parseField(s: string, max: number): ParsedField | null {
  if (s === "*") return "*";
  if (/^\d+$/.test(s)) {
    const n = Number.parseInt(s, 10);
    return n >= 0 && n <= max ? n : null;
  }
  return null;
}

function matches(field: ParsedField, current: number): boolean {
  return field === "*" || field === current;
}

/**
 * 计算给定 cron 表达式相对于 `now` 的下一次触发时间。
 * 不支持复杂表达式时返回 null。搜索范围限制在 7 天内。
 */
export function nextCronRun(cron: string, now: Date = new Date()): Date | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;

  const minute = parseField(parts[0], MAX.minute);
  const hour = parseField(parts[1], MAX.hour);
  const dom = parseField(parts[2], MAX.dom);
  const month = parseField(parts[3], MAX.month);
  const dow = parseField(parts[4], MAX.dow);

  if (minute === null || hour === null || dom === null || month === null || dow === null) {
    return null;
  }

  // 暂不支持指定月 / 月内某日 — 预设场景里这两位始终是 "*"
  if (dom !== "*" || month !== "*") return null;

  const next = new Date(now);
  next.setSeconds(0, 0);
  next.setMinutes(next.getMinutes() + 1);

  const limit = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);

  while (next <= limit) {
    if (
      matches(minute, next.getMinutes()) &&
      matches(hour, next.getHours()) &&
      matches(dow, next.getDay())
    ) {
      return next;
    }
    next.setMinutes(next.getMinutes() + 1);
  }
  return null;
}

/**
 * 友好显示 cron 表达式（如 `0 9 * * 1` → "每周一 09:00"）。
 * 与 nextCronRun 同样的限制：复杂表达式返回 null，调用方原样展示。
 */
export function describeCron(cron: string): string | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;

  const [minStr, hourStr, domStr, monStr, dowStr] = parts;
  const minute = parseField(minStr, MAX.minute);
  const hour = parseField(hourStr, MAX.hour);
  const dom = parseField(domStr, MAX.dom);
  const month = parseField(monStr, MAX.month);
  const dow = parseField(dowStr, MAX.dow);

  if (minute === null || hour === null || dom === null || month === null || dow === null) {
    return null;
  }
  if (dom !== "*" || month !== "*") return null;

  const pad = (n: number) => String(n).padStart(2, "0");
  const weekdayName = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

  // 每小时（M * * * *）
  if (hour === "*" && dow === "*") {
    if (minute === "*") return "每分钟";
    return `每小时第 ${minute} 分钟`;
  }
  // 每周指定日（M H * * D）
  if (dow !== "*" && typeof hour === "number" && typeof minute === "number") {
    return `每${weekdayName[dow]} ${pad(hour)}:${pad(minute)}`;
  }
  // 每天（M H * * *）
  if (dow === "*" && typeof hour === "number" && typeof minute === "number") {
    return `每天 ${pad(hour)}:${pad(minute)}`;
  }

  return null;
}
