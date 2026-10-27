"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Radio, Select, Skeleton, Tag } from "antd";
import type { ECharts } from "echarts";
import { GraphViewportActions } from "@/app/assets/[assetId]/_components/GraphViewportActions";
import { getApiData, type AbilityAnalysis, type OccupationalAbilityItem, type OccupationalWorkTask } from "@/lib/api";
import { ABILITY_COLORS, ABILITY_VIEWS, buildOccupationalHierarchy, type AbilityHierarchyNode, type AbilityView } from "./abilityHierarchy";
import { abilityGraphOption } from "./abilityGraphOptions";

async function completeList<T>(path: string): Promise<T[]> {
  const data: T[] = [];
  for (let page = 1; ; page++) {
    const result = await getApiData<T[]>(path, [], { page: String(page), pageSize: "200" });
    if (!result.ok) throw new Error(result.error || "数据加载失败");
    data.push(...result.data);
    if (result.total !== null && data.length >= result.total) return data;
    if (result.data.length < 200) {
      if (result.total !== null && data.length < result.total) throw new Error("数据未完整加载，请重试");
      return data;
    }
  }
}

export function OccupationalAbilityGraph({ analysis }: { analysis: AbilityAnalysis }) {
  const [state, setState] = useState<{ tasks: OccupationalWorkTask[]; items: OccupationalAbilityItem[]; loading: boolean; error: string | null }>({ tasks: [], items: [], loading: true, error: null });
  const [taskId, setTaskId] = useState<string>("all");
  const [view, setView] = useState<AbilityView>("tree");
  const [reload, setReload] = useState(0);
  const [reset, setReset] = useState(0);
  const chart = useRef<ECharts | null>(null);
  const viewport = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let active = true;
    setState({ tasks: [], items: [], loading: true, error: null });
    setTaskId("all");
    const base = `/api/record-assets/ability-analyses/${analysis.id}`;
    Promise.all([completeList<OccupationalWorkTask>(`${base}/tasks`), completeList<OccupationalAbilityItem>(`${base}/ability-items`)]).then(([tasks, items]) => {
      if (active) setState({ tasks, items, loading: false, error: null });
    }).catch((error: unknown) => {
      if (active) setState({ tasks: [], items: [], loading: false, error: error instanceof Error ? error.message : "数据加载失败" });
    });
    return () => { active = false; };
  }, [analysis.id, reload]);
  const hierarchy = useMemo(() => {
    try {
      // Build the full source tree once, then select a branch without regrouping.
      const root = buildOccupationalHierarchy(analysis, state.tasks, state.items);
      if (taskId === "all") return { root, error: null };
      const children = root.children?.filter((node) => node.sourceId === taskId) ?? [];
      return { root: { ...root, children, value: children.reduce((sum, node) => sum + node.value, 0) }, error: null };
    } catch (error) {
      return { root: null, error: error instanceof Error ? error.message : "层级数据错误" };
    }
  }, [analysis, state.tasks, state.items, taskId]);
  const error = state.error || hierarchy.error;
  const root = hierarchy.root;
  const name = ABILITY_VIEWS.find((v) => v.value === view)!.label;
  const download = () => {
    if (!chart.current) return;
    const link = document.createElement("a");
    link.href = chart.current.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#fff" });
    link.download = `${analysis.major_name || "职业能力分析"}-${name}.png`;
    link.click();
  };
  return <div className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Radio.Group aria-label="图谱视图" optionType="button" buttonStyle="solid" options={[...ABILITY_VIEWS]} value={view} onChange={(event) => setView(event.target.value as AbilityView)} />
      <div className="flex items-center gap-2">
        <Button onClick={() => { setReset((n) => n + 1); viewport.current?.scrollTo(0, 0); }}>复位视图</Button>
        <GraphViewportActions title={`能力图谱${name}`} disabled={!root?.value || !!error || state.loading} onDownload={download} downloadLabel="下载当前视图 PNG">
          {root ? <HierarchyCanvas root={root} view={view} reset={reset} fullscreen /> : null}
        </GraphViewportActions>
      </div>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Select aria-label="典型工作任务" className="w-full max-w-md" value={taskId} loading={state.loading}
        options={[{ value: "all", label: "全部任务" }, ...state.tasks.map((task) => ({ value: task.id, label: task.task_name }))]} onChange={setTaskId} />
      <div aria-label="能力图例">
        {(["P", "G", "S", "D"] as const).map((category) => <Tag key={category} color={ABILITY_COLORS[category]}>{category} {({ P: "职业能力", G: "通用能力", S: "社会能力", D: "发展能力" })[category]}</Tag>)}
      </div>
    </div>
    <div className="text-text-muted text-xs" role="status">
      {root ? `${root.children?.length ?? 0} 个任务 · ${root.value} 项能力 · ` : ""}
      {({ tree: "缩放平移 · 点击节点展开或收起 · 滚动查看全部能力", sunburst: "点击扇区下钻 · 点击中心返回", treemap: "点击区块下钻 · 面包屑返回", graph: "拖动节点 · 缩放平移 · 悬浮查看邻接关系" })[view]}
    </div>
    {state.loading ? <Skeleton active paragraph={{ rows: 8 }} /> : error ? <Alert type="error" showIcon title="加载能力图谱失败" description={error} action={<Button onClick={() => setReload((n) => n + 1)}>重试</Button>} /> : !root?.value ? <Empty description="暂无能力图谱数据" /> :
      <div ref={viewport} className="overflow-auto rounded-md border border-slate-200" style={{ height: "calc(100dvh - 285px)", minHeight: 360 }}>
        <HierarchyCanvas root={root} view={view} reset={reset} chartRef={chart} />
      </div>}
  </div>;
}

function HierarchyCanvas({ root, view, reset, fullscreen = false, chartRef }: {
  root: AbilityHierarchyNode; view: AbilityView; reset: number; fullscreen?: boolean;
  chartRef?: { current: ECharts | null };
}) {
  const host = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let disposed = false;
    let instance: ECharts | null = null;
    let observer: ResizeObserver | null = null;
    import("echarts").then((echarts) => {
      if (disposed || !host.current) return;
      instance = echarts.init(host.current, undefined, { renderer: "canvas" });
      if (chartRef) chartRef.current = instance;
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      instance.setOption(abilityGraphOption(root, view, reduced));
      observer = new ResizeObserver(() => instance?.resize());
      observer.observe(host.current);
    });
    return () => { disposed = true; observer?.disconnect(); instance?.dispose(); if (chartRef) chartRef.current = null; };
  }, [root, view, reset, chartRef]);
  const height = view === "tree" ? Math.max(620, root.value * 26) : fullscreen ? "100%" : 800;
  return <div className={fullscreen ? "h-full overflow-auto" : undefined}>
    <div ref={host} role="img" aria-label={`能力图谱${ABILITY_VIEWS.find((v) => v.value === view)!.label}`} data-view={view}
      style={{ width: "100%", minWidth: view === "tree" ? 1180 : 900, height, minHeight: 600 }} />
  </div>;
}
