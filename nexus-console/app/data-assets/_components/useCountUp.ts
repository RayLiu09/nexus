"use client";

/**
 * Light-weight count-up hook for the masthead + per-card KPIs.
 *
 * Animates from 0 → `target` over `durationMs`. Uses
 * `requestAnimationFrame` + a simple easeOutQuart curve so the final
 * digits don't whiplash. Respects `prefers-reduced-motion` by skipping
 * the animation entirely.
 */
import { useEffect, useState } from "react";


export function useCountUp(target: number, durationMs: number = 900): number {
  const [value, setValue] = useState<number>(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const prefersReduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (prefersReduced) {
      setValue(target);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      const t = Math.min(1, elapsed / durationMs);
      // easeOutQuart — fast initial growth, gentle landing.
      const eased = 1 - Math.pow(1 - t, 4);
      setValue(Math.round(target * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return value;
}
