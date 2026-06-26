"use client";

/**
 * Board shell — masthead + asymmetric card grid + footer ledger.
 *
 * Grid choice:
 * - At ≥ xl breakpoints the first card spans **2/3** of the row (`xl:col-span-2`)
 *   so the most-trafficked domain reads as the hero — D1 by mock-data
 *   convention. Other cards fill a regular 3-up grid below.
 * - At md it collapses to 2-up. At sm to 1-up. No overflow scroll dance.
 *
 * Animation: each card receives an explicit `delayMs` so the reveal
 * comes in as a wave from top-left to bottom-right.
 */

import type { BoardOverview, DomainCard } from "@/lib/data-assets/mock";
import { BoardMasthead } from "./BoardMasthead";
import { DataAssetCard } from "./DataAssetCard";


type Props = {
  overview: BoardOverview;
  cards: DomainCard[];
};


export function DataAssetsBoard({ overview, cards }: Props) {
  return (
    <div className="-mx-[var(--space-4)] -mt-[var(--space-4)] flex flex-col">
      <BoardMasthead overview={overview} />

      <main
        className="grid grid-cols-1 gap-5 px-6 py-8 md:grid-cols-2 lg:px-10 xl:grid-cols-3"
        aria-label="数据资产大类列表"
      >
        {cards.map((card, idx) => (
          <div
            key={card.code}
            className={idx === 0 ? "xl:col-span-2" : ""}
          >
            <DataAssetCard card={card} delayMs={120 + idx * 90} />
          </div>
        ))}
      </main>

      {/* Footer ledger — global review_required breakdown by domain */}
      <footer
        className="mx-6 mb-10 mt-2 rounded-lg border border-line bg-surface lg:mx-10"
        style={{
          backgroundImage:
            "linear-gradient(180deg, rgba(15,23,42,0.02) 0%, transparent 100%)",
        }}
      >
        <div className="flex flex-col gap-2 border-b border-line px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
          <h3 className="font-serif text-base font-semibold text-[var(--text)]">
            待审项一览
            <span className="ml-3 text-[10px] font-bold uppercase tracking-[0.2em] text-muted">
              Awaiting Review · by Domain
            </span>
          </h3>
          <p className="text-xs text-muted">
            指标基于 governance_result.status = <code>review_required</code> 与各领域表 quality_flags
          </p>
        </div>
        <ul className="grid grid-cols-2 list-none divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0 lg:grid-cols-6">
          {cards.map((card) => (
            <li
              key={card.code}
              className="flex items-center justify-between gap-4 px-5 py-4"
            >
              <div className="min-w-0">
                <p className="truncate text-[10px] font-bold uppercase tracking-[0.18em] text-muted">
                  {card.code}
                </p>
                <p className="truncate text-sm font-medium text-[var(--text)]">
                  {card.name}
                </p>
              </div>
              <span
                className="font-serif text-2xl font-semibold tabular-nums"
                style={{ color: card.review > 0 ? "var(--warning-600)" : "var(--text-muted)" }}
              >
                {card.review}
              </span>
            </li>
          ))}
        </ul>
      </footer>
    </div>
  );
}
