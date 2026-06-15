"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, InputNumber, Input, Segmented, Select, TimePicker } from "antd";
import dayjs, { type Dayjs } from "dayjs";

import { describeCron, nextCronRun } from "@/lib/cron/nextRun";

export type CronMode = "off" | "hourly" | "daily" | "weekly" | "custom";

interface CronPickerProps {
  value: string;
  onChange: (cron: string) => void;
  /** 当模式为 off 时是否允许 —— 默认允许，nas/crawler/database 都可以"无定时" */
  allowOff?: boolean;
}

const MODE_OPTIONS: { label: string; value: CronMode }[] = [
  { label: "不定时", value: "off" },
  { label: "每小时", value: "hourly" },
  { label: "每天", value: "daily" },
  { label: "每周", value: "weekly" },
  { label: "自定义 cron", value: "custom" },
];

const WEEKDAY_OPTIONS = [
  { label: "周一", value: 1 },
  { label: "周二", value: 2 },
  { label: "周三", value: 3 },
  { label: "周四", value: 4 },
  { label: "周五", value: 5 },
  { label: "周六", value: 6 },
  { label: "周日", value: 0 },
];

/** 把 cron 字符串反推回 mode + 字段值。识别失败回退到 custom 模式 */
function detectMode(cron: string): {
  mode: CronMode;
  minute: number;
  hour: number;
  weekday: number;
  raw: string;
} {
  const fallback = {
    mode: "custom" as CronMode,
    minute: 0,
    hour: 9,
    weekday: 1,
    raw: cron,
  };
  if (!cron.trim()) return { ...fallback, mode: "off", raw: "" };

  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return fallback;
  const [m, h, dom, mon, dow] = parts;
  const isInt = (s: string) => /^\d+$/.test(s);
  if (dom !== "*" || mon !== "*") return fallback;

  // hourly: M * * * *
  if (isInt(m) && h === "*" && dow === "*") {
    return { mode: "hourly", minute: Number(m), hour: 0, weekday: 1, raw: cron };
  }
  // daily: M H * * *
  if (isInt(m) && isInt(h) && dow === "*") {
    return { mode: "daily", minute: Number(m), hour: Number(h), weekday: 1, raw: cron };
  }
  // weekly: M H * * D
  if (isInt(m) && isInt(h) && isInt(dow)) {
    return {
      mode: "weekly",
      minute: Number(m),
      hour: Number(h),
      weekday: Number(dow),
      raw: cron,
    };
  }
  return fallback;
}

export function CronPicker({ value, onChange, allowOff = true }: CronPickerProps) {
  const initial = useMemo(() => detectMode(value), [value]);
  const [mode, setMode] = useState<CronMode>(initial.mode);
  const [minute, setMinute] = useState<number>(initial.minute);
  const [hour, setHour] = useState<number>(initial.hour);
  const [weekday, setWeekday] = useState<number>(initial.weekday);
  const [custom, setCustom] = useState<string>(initial.raw);

  // 模式或字段变化时，向父级回传 cron 字符串
  useEffect(() => {
    let next = "";
    if (mode === "hourly") next = `${minute} * * * *`;
    else if (mode === "daily") next = `${minute} ${hour} * * *`;
    else if (mode === "weekly") next = `${minute} ${hour} * * ${weekday}`;
    else if (mode === "custom") next = custom.trim();
    else next = ""; // off
    if (next !== value) onChange(next);
    // 故意只 watch 字段；value 反向同步由外部初始化处理
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, minute, hour, weekday, custom]);

  // 实时预览
  const preview = useMemo(() => {
    const current =
      mode === "hourly"
        ? `${minute} * * * *`
        : mode === "daily"
          ? `${minute} ${hour} * * *`
          : mode === "weekly"
            ? `${minute} ${hour} * * ${weekday}`
            : mode === "custom"
              ? custom.trim()
              : "";
    if (!current) return null;
    const next = nextCronRun(current);
    return {
      cron: current,
      humanized: describeCron(current),
      nextRun: next,
    };
  }, [mode, minute, hour, weekday, custom]);

  const modeOptions = allowOff ? MODE_OPTIONS : MODE_OPTIONS.filter((o) => o.value !== "off");

  return (
    <div className="grid gap-3">
      <Segmented
        block
        options={modeOptions}
        value={mode}
        onChange={(v) => setMode(v as CronMode)}
      />

      {mode === "off" && (
        <div className="text-text-secondary text-xs">
          不配置定时同步，仅依赖手动触发或外部事件驱动。
        </div>
      )}

      {mode === "hourly" && (
        <div className="flex items-center gap-2 text-sm">
          <span>每小时第</span>
          <InputNumber
            min={0}
            max={59}
            value={minute}
            onChange={(v) => setMinute(typeof v === "number" ? v : 0)}
          />
          <span>分钟触发</span>
        </div>
      )}

      {(mode === "daily" || mode === "weekly") && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {mode === "weekly" && (
            <>
              <span>每</span>
              <Select
                style={{ width: 100 }}
                value={weekday}
                onChange={(v) => setWeekday(v)}
                options={WEEKDAY_OPTIONS}
              />
            </>
          )}
          {mode === "daily" && <span>每天</span>}
          <span>{mode === "weekly" ? "" : "在"}</span>
          <TimePicker
            format="HH:mm"
            minuteStep={5}
            value={makeTime(hour, minute)}
            onChange={(t) => {
              if (t) {
                setHour(t.hour());
                setMinute(t.minute());
              }
            }}
            allowClear={false}
          />
          <span>触发</span>
        </div>
      )}

      {mode === "custom" && (
        <div className="grid gap-1">
          <Input
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="例：0 */6 * * *"
          />
          <div className="text-text-muted text-xs">
            标准 5 段 cron（分 时 日 月 周）。复杂表达式如步长、范围、列表需自行验证。
          </div>
        </div>
      )}

      {preview && preview.cron && (
        <Alert
          type={preview.nextRun ? "success" : "info"}
          showIcon
          title={
            <span className="text-xs">
              当前 cron：<code className="font-mono">{preview.cron}</code>
              {preview.humanized && <span className="ml-2">（{preview.humanized}）</span>}
            </span>
          }
          description={
            preview.nextRun ? (
              <span className="text-xs">下次将于 {formatPreviewTime(preview.nextRun)} 触发</span>
            ) : (
              <span className="text-xs">无法预测下次触发时间，请自行验证 cron 表达式</span>
            )
          }
        />
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────

function makeTime(h: number, m: number): Dayjs {
  return dayjs().hour(h).minute(m).second(0);
}

function formatPreviewTime(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
