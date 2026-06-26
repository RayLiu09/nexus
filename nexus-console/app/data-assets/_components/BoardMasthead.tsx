"use client";

/**
 * Editorial masthead — the page's hero strip.
 *
 * Layout: left = "issue masthead" (vol/issue + datestamp + page title);
 * right = three oversized KPI numerals separated by hairlines. The
 * numerals lean on `tabular-nums` so trailing digits don't wiggle as the
 * count animates in.
 *
 * Style decisions kept here (not in globals.css) so the masthead can
 * evolve without disturbing the rest of the console.
 */

import { useEffect, useState } from "react";
import { Tooltip } from "antd";
import { ArrowUpRight, AlertCircle, Sparkles } from "lucide-react";
import type { BoardOverview } from "@/lib/data-assets/mock";
import { useCountUp } from "./useCountUp";


type Props = { overview: BoardOverview };

const FORMATTER = new Intl.NumberFormat("en-US");
const DATE_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "long", day: "numeric",
});


export function BoardMasthead({ overview }: Props) {
  // Defer the rendered datestamp to the client to avoid a hydration
  // mismatch when the server / client clock cross a midnight boundary.
  const [datestamp, setDatestamp] = useState("");
  useEffect(() => {
    setDatestamp(DATE_FORMATTER.format(new Date(overview.generatedAt)));
  }, [overview.generatedAt]);

  const records = useCountUp(overview.totalRecords);
  const assets = useCountUp(overview.totalAssets);
  const fresh = useCountUp(overview.weeklyFresh);

  return (
    <header
      className="relative overflow-hidden border-y border-line bg-surface"
      style={{
        // Subtle paper-grain so the white slab doesn't read as a plain CSS bg.
        backgroundImage: "radial-gradient(circle at 1px 1px, rgba(15,23,42,0.04) 1px, transparent 0)",
        backgroundSize: "16px 16px",
      }}
    >
      <div className="grid grid-cols-1 gap-6 px-6 py-8 lg:grid-cols-12 lg:gap-10 lg:px-10 lg:py-10">
        {/* Left — issue masthead */}
        <div className="lg:col-span-5">
          <p
            className="text-[10px] font-bold uppercase tracking-[0.32em] text-muted"
            style={{ animation: "ed-fade 0.55s ease-out both", animationDelay: "0ms" }}
          >
            Nexus · Data Asset Atlas
          </p>
          <h1
            className="mt-3 font-serif text-[40px] leading-[1.05] font-semibold text-[var(--text)] sm:text-[52px]"
            style={{ animation: "ed-fade 0.6s ease-out both", animationDelay: "60ms" }}
          >
            数据资产 <span className="text-muted">总览</span>
          </h1>
          <p
            className="mt-3 max-w-[36ch] text-sm text-[var(--text-muted)]"
            style={{ animation: "ed-fade 0.6s ease-out both", animationDelay: "120ms" }}
          >
            按治理大类汇总平台所有数据资产 — 每周快照，含子类条目数、增量与待审条数。
          </p>
          <div
            className="mt-6 flex items-center gap-3 text-[11px] tracking-[0.18em] text-muted uppercase"
            style={{ animation: "ed-fade 0.55s ease-out both", animationDelay: "180ms" }}
          >
            <span className="font-semibold text-[var(--text)]">{overview.issueNo}</span>
            <span aria-hidden className="h-px w-8 bg-line" />
            <time>{datestamp || "—"}</time>
          </div>
        </div>

        {/* Right — 3 oversized KPI numerals */}
        <div className="lg:col-span-7">
          <dl className="grid grid-cols-3 divide-x divide-line">
            <KpiCell
              label="记录总条数"
              shadow="Total Records"
              value={records}
              raw={overview.totalRecords}
              delayMs={240}
              hint="所有领域表的累计记录数 (包含 review_required)"
              icon={<Sparkles size={14} aria-hidden />}
            />
            <KpiCell
              label="资产数 (asset)"
              shadow="Distinct Assets"
              value={assets}
              raw={overview.totalAssets}
              delayMs={300}
              hint="对外可检索的标准化资产单元数"
              icon={<ArrowUpRight size={14} aria-hidden />}
            />
            <KpiCell
              label="待审 review_required"
              shadow="Awaiting Review"
              value={overview.totalReview}
              raw={overview.totalReview}
              delayMs={360}
              hint="阻塞性 quality_flag 或 governance blocking finding 触发"
              icon={<AlertCircle size={14} aria-hidden />}
              accent
            />
          </dl>
          <p
            className="mt-4 text-xs text-muted"
            style={{ animation: "ed-fade 0.5s ease-out both", animationDelay: "420ms" }}
          >
            本周新入 / 重新摄入：
            <span className="ml-1 font-semibold text-[var(--text)] tabular-nums">
              {FORMATTER.format(fresh)}
            </span>
            <span className="ml-1">条</span>
            <span aria-hidden className="mx-3 inline-block h-3 w-px align-middle bg-line" />
            覆盖 <span className="font-semibold text-[var(--text)] tabular-nums">
              {overview.domainCount}</span> 个大类
          </p>
        </div>
      </div>

      <style>{`
        @keyframes ed-fade {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </header>
  );
}


function KpiCell({
  label, shadow, value, raw, delayMs, hint, icon, accent = false,
}: {
  label: string;
  shadow: string;
  value: number;
  raw: number;
  delayMs: number;
  hint: string;
  icon: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <Tooltip title={hint} placement="bottom">
      <div
        className="flex flex-col gap-2 px-5 first:pl-0 last:pr-0"
        style={{ animation: "ed-fade 0.6s ease-out both", animationDelay: `${delayMs}ms` }}
      >
        <dt className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.24em] text-muted">
          {icon}
          <span>{shadow}</span>
        </dt>
        <dd
          className={`font-serif text-[44px] leading-none font-semibold tabular-nums sm:text-[56px] ${
            accent ? "text-[var(--danger-600)]" : "text-[var(--text)]"
          }`}
          aria-label={`${label}: ${FORMATTER.format(raw)}`}
        >
          {FORMATTER.format(value)}
        </dd>
        <dd className="text-xs text-[var(--text-muted)]">{label}</dd>
      </div>
    </Tooltip>
  );
}
