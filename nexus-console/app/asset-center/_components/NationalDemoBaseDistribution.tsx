"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Skeleton } from "antd";
import type { ECharts, EChartsOption } from "echarts";
import type { EcommerceDemoBaseAggregate } from "@/lib/api";

type Props = {
  aggregate: EcommerceDemoBaseAggregate;
  selectedProvince?: string;
  onProvinceSelect: (code?: string) => void;
};

type ProvinceFeature = {
  properties: { adcode?: number; name?: string };
};

export function NationalDemoBaseDistribution(props: Props) {
  const selected = props.aggregate.filter_options.provinces.find(
    (item) => item.province_code === props.selectedProvince,
  );
  return (
    <section className="flex min-w-0 flex-col gap-3" aria-label="国家示范基地分布">
      {props.selectedProvince && (
        <div className="flex items-center gap-2 text-sm">
          <span>当前省份：{selected?.province_name ?? props.selectedProvince}</span>
          <Button size="small" onClick={() => props.onProvinceSelect()}>
            全部地区
          </Button>
        </div>
      )}
      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <DistributionChart {...props} kind="bar" />
        <DistributionChart {...props} kind="map" />
      </div>
      <p className="text-text-muted text-xs">
        图表展示当前条件匹配的基地数量；点击省份查看名录，再次点击或选择“全部地区”可清除省份条件。
      </p>
    </section>
  );
}

function DistributionChart({
  aggregate,
  selectedProvince,
  onProvinceSelect,
  kind,
}: Props & { kind: "bar" | "map" }) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let disposed = false;
    let chart: ECharts | null = null;
    let observer: ResizeObserver | null = null;
    const abort = new AbortController();
    async function renderChart() {
      const echarts = await import("echarts");
      let option: EChartsOption;
      const names = new Map(
        aggregate.filter_options.provinces.map((item) => [item.province_code, item.province_name]),
      );
      const counts = new Map(
        aggregate.province_counts.map((item) => [item.province_code, item.count]),
      );
      if (kind === "map") {
        const result = await fetch("/maps/china-provinces.json", { signal: abort.signal });
        if (!result.ok) throw new Error("map unavailable");
        const geoJson = await result.json();
        if (!Array.isArray(geoJson.features)) throw new Error("invalid map");
        const features: ProvinceFeature[] = geoJson.features;
        if (disposed) return;
        echarts.registerMap("nexus-china-provinces", geoJson);
        const data = features.map((feature) => {
          const code = String(feature.properties.adcode ?? "");
          const missing = !names.has(code);
          return {
            name: feature.properties.name ?? "",
            code,
            value: missing ? Number.NaN : (counts.get(code) ?? 0),
            missing,
            selected: code === selectedProvince,
            ...(missing ? { itemStyle: { areaColor: "#e2e8f0" } } : {}),
          };
        });
        option = {
          tooltip: {
            trigger: "item",
            renderMode: "richText",
            formatter: (params) => {
              const event = Array.isArray(params) ? params[0] : params;
              const item = event.data as
                | { name: string; value: number; missing: boolean }
                | undefined;
              return !item
                ? ""
                : `${item.name}\n${item.missing ? "当前数据未收录" : `当前条件匹配：${item.value} 个基地`}`;
            },
          },
          visualMap: {
            min: 0,
            max: Math.max(1, ...aggregate.province_counts.map((item) => item.count)),
            left: 0,
            bottom: 12,
            text: ["多", "少"],
            itemHeight: 90,
            itemWidth: 10,
            inRange: { color: ["#dbeafe", "#60a5fa", "#1d4ed8"] },
          },
          series: [
            {
              type: "map",
              map: "nexus-china-provinces",
              roam: false,
              selectedMode: "single",
              layoutCenter: ["54%", "48%"],
              layoutSize: "100%",
              itemStyle: { borderColor: "#fff", borderWidth: 0.8 },
              emphasis: { label: { show: true }, itemStyle: { areaColor: "#fbbf24" } },
              select: { label: { show: true }, itemStyle: { areaColor: "#f59e0b" } },
              data,
            },
          ],
        };
      } else {
        const rows = [...aggregate.province_counts].sort(
          (a, b) => b.count - a.count || a.province_code.localeCompare(b.province_code),
        );
        option = {
          tooltip: { trigger: "axis", renderMode: "richText", axisPointer: { type: "shadow" } },
          grid: { left: 32, right: 16, top: 30, bottom: 72, containLabel: false },
          xAxis: {
            type: "category",
            data: rows.map((item) => item.province_name),
            axisLabel: { interval: 0, rotate: 55, fontSize: 10 },
            axisTick: { show: false },
          },
          yAxis: {
            type: "value",
            name: "基地数量（个）",
            minInterval: 1,
            splitLine: { lineStyle: { color: "#edf2f7" } },
          },
          series: [
            {
              type: "bar",
              barMaxWidth: 24,
              label: { show: true, position: "top", fontSize: 10, color: "#475569" },
              data: rows.map((item) => ({
                name: item.province_name,
                value: item.count,
                code: item.province_code,
                itemStyle: {
                  color: item.province_code === selectedProvince ? "#f59e0b" : "#3b82f6",
                  borderRadius: [3, 3, 0, 0],
                },
              })),
            },
          ],
        };
      }
      if (disposed || !host.current) return;
      chart = echarts.init(host.current, undefined, { renderer: "svg" });
      chart.setOption(option);
      chart.on("click", (params) => {
        const data = params.data;
        if (data && typeof data === "object" && "code" in data) {
          const code = String(data.code);
          if (/^\d{6}$/.test(code)) onProvinceSelect(code);
        }
      });
      observer = new ResizeObserver(() => chart?.resize());
      observer.observe(host.current);
      setState("ready");
    }
    void renderChart().catch(() => {
      if (!disposed) setState("error");
    });
    return () => {
      disposed = true;
      abort.abort();
      observer?.disconnect();
      chart?.dispose();
    };
  }, [aggregate, selectedProvince, onProvinceSelect, kind, attempt]);

  return (
    <article className="border-line bg-surface min-w-0 rounded-md border p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-text text-sm font-semibold">
          {kind === "map" ? "省份分布地图" : "省份基地数量"}
        </h3>
        <span className="text-text-muted text-xs">当前条件</span>
      </div>
      <div className="relative min-w-0 overflow-x-auto">
        <div
          ref={host}
          role="img"
          aria-label={kind === "map" ? "中国省份基地分布地图" : "省份基地数量柱状图"}
          data-chart-state={state}
          className={kind === "map" ? "h-[360px] w-full" : "h-[360px] w-full min-w-[540px]"}
        />
        {state === "loading" && (
          <div className="bg-surface absolute inset-0 p-8">
            <Skeleton active paragraph={{ rows: 6 }} />
          </div>
        )}
        {state === "error" && (
          <div className="bg-surface absolute inset-0 flex flex-col items-center justify-center gap-3 text-sm">
            <p>图表加载失败，仍可通过列表查看基地。</p>
            <Button
              onClick={() => {
                setState("loading");
                setAttempt((value) => value + 1);
              }}
            >
              重新加载图表
            </Button>
          </div>
        )}
      </div>
      {kind === "map" && (
        <p className="text-text-muted mt-2 flex items-center gap-1.5 text-xs">
          <span className="inline-block h-2.5 w-2.5 bg-slate-200" />
          当前数据未收录；蓝色地区为已收录地区，浅色可表示当前条件匹配为零。
        </p>
      )}
    </article>
  );
}
