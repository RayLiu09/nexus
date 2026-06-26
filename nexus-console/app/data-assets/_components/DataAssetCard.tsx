"use client";

/**
 * Single domain-classification card on the Atlas board.
 *
 * Layout (top → bottom):
 *  1. Header row: chip-style code + zh-CN name, watermark code in the
 *     top-right corner, hairline below
 *  2. Hero numeral: total count (count-up) + caption + trend chip
 *  3. Subcategory ledger: 2- or 3-line list, hairline-separated,
 *     right-aligned tabular numerals
 *  4. Footer chip strip: review_required count + last-7-days fresh count
 *
 * The accent colour comes from `--domain-d{slot}` tokens declared in
 * `app/globals.css`. The component injects two CSS variables (`--accent`,
 * `--accent-bg`) so the rest of the styling stays in plain Tailwind
 * classes / token references and the card composes with whatever palette
 * the board passes in.
 */

import type { CSSProperties } from "react";
import { Tag, Tooltip } from "antd";
import { TrendingDown, TrendingUp, AlertOctagon, ArrowUpRight } from "lucide-react";
import type { DomainCard } from "@/lib/data-assets/mock";
import { useCountUp } from "./useCountUp";


type Props = {
  card: DomainCard;
  /** Stagger animation delay so cards reveal in a wave. */
  delayMs: number;
};

const NUM = new Intl.NumberFormat("en-US");


export function DataAssetCard({ card, delayMs }: Props) {
  const total = useCountUp(card.total);
  const trendUp = card.delta.pct >= 0;
  const accentStyle = {
    "--accent": `var(--domain-d${card.slot})`,
    "--accent-bg": `var(--domain-d${card.slot}-bg)`,
    animationDelay: `${delayMs}ms`,
  } as CSSProperties;

  return (
    <article
      className={`
        group relative flex flex-col gap-5 overflow-hidden rounded-lg border border-line bg-surface p-6
        transition-[transform,box-shadow,border-color] duration-300
        hover:-translate-y-0.5 hover:border-[var(--accent)]
        hover:shadow-[0_18px_40px_-24px_var(--accent)]
      `}
      style={{ ...accentStyle, animation: "card-rise 0.5s ease-out both" }}
      aria-labelledby={`dac-${card.code}-name`}
    >
      {/* Watermark code — purely decorative; aria-hidden so SR users skip it. */}
      <span
        aria-hidden
        className="pointer-events-none absolute -right-2 -top-3 font-serif text-[120px] font-black leading-none tracking-tight text-[var(--accent-bg)] opacity-90 select-none"
      >
        {card.code}
      </span>

      {/* Top hairline accent — only visible on hover */}
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-[3px] origin-left scale-x-0 bg-[var(--accent)] transition-transform duration-500 group-hover:scale-x-100"
      />

      {/* Header */}
      <header className="relative flex items-start gap-3">
        <span
          className="rounded-md px-2 py-1 text-[10px] font-bold tracking-[0.2em] uppercase"
          style={{ color: "var(--accent)", backgroundColor: "var(--accent-bg)" }}
        >
          {card.code}
        </span>
        <div className="flex-1">
          <h2
            id={`dac-${card.code}-name`}
            className="font-serif text-lg font-semibold leading-tight text-[var(--text)]"
          >
            {card.name}
          </h2>
          <p className="mt-0.5 text-[10px] font-bold uppercase tracking-[0.18em] text-muted">
            {card.shadow}
          </p>
        </div>
      </header>

      {/* Hero numeral + caption */}
      <div className="relative">
        <div className="flex items-end gap-3">
          <span
            className="font-serif text-[56px] leading-none font-semibold tabular-nums text-[var(--text)]"
            aria-label={`${card.name} 累计记录数 ${NUM.format(card.total)}`}
          >
            {NUM.format(total)}
          </span>
          <DeltaChip trendUp={trendUp} pct={card.delta.pct} label={card.delta.label} />
        </div>
        <p className="mt-3 max-w-[40ch] text-[13px] leading-relaxed text-[var(--text-muted)]">
          {card.caption}
        </p>
      </div>

      {/* Subcategory ledger */}
      <ul className="relative -mx-1 list-none divide-y divide-line border-y border-line">
        {card.sub.map((s, idx) => (
          <li
            key={s.code}
            className="group/row flex items-center gap-3 px-1 py-2.5 transition-colors hover:bg-[var(--accent-bg)]"
            style={{ animation: "row-in 0.4s ease-out both", animationDelay: `${delayMs + 80 * (idx + 1)}ms` }}
          >
            <span
              aria-hidden
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: "var(--accent)" }}
            />
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-medium text-[var(--text)]">
                {s.name}
              </p>
              <p className="truncate text-[10px] uppercase tracking-[0.16em] text-muted">
                {s.shadow}
              </p>
            </div>
            <Tooltip title={`本周新增 ${s.fresh} 条`} placement="left">
              <span className="hidden text-[11px] text-muted tabular-nums sm:inline">
                +{s.fresh}
              </span>
            </Tooltip>
            <span className="font-serif text-base font-semibold tabular-nums text-[var(--text)] min-w-[64px] text-right">
              {NUM.format(s.count)}
            </span>
          </li>
        ))}
      </ul>

      {/* Footer chips */}
      <footer className="relative flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          {card.review > 0 ? (
            <Tag color="orange" icon={<AlertOctagon size={12} aria-hidden />}
                 className="!m-0 !inline-flex !items-center !gap-1">
              {card.review} 条待审
            </Tag>
          ) : (
            <Tag className="!m-0">无待审</Tag>
          )}
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-[var(--accent)] font-medium hover:underline"
          aria-label={`查看 ${card.name} 详情`}
        >
          查看明细
          <ArrowUpRight size={14} aria-hidden />
        </button>
      </footer>

      <style>{`
        @keyframes card-rise {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes row-in {
          from { opacity: 0; transform: translateX(-6px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </article>
  );
}


function DeltaChip({
  trendUp, pct, label,
}: { trendUp: boolean; pct: number; label: string }) {
  const Icon = trendUp ? TrendingUp : TrendingDown;
  return (
    <Tooltip title={label}>
      <span
        className={`
          inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums
          ${trendUp
            ? "bg-[color:var(--success-50,#f0fdf4)] text-[var(--success-600)]"
            : "bg-[color:var(--warning-50,#fff7ed)] text-[var(--warning-600)]"}
        `}
      >
        <Icon size={12} aria-hidden />
        {trendUp ? "+" : ""}{pct.toFixed(1)}%
      </span>
    </Tooltip>
  );
}
