import type { EChartsOption } from "echarts";
import { ABILITY_COLORS, flattenAbilityHierarchy, type AbilityHierarchyNode, type AbilityView } from "./abilityHierarchy";

const escape = (value: string) => value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const wrap = (text: string, width = 10) => Array.from(text).reduce((parts, c, i) => parts + (i && i % width === 0 ? "\n" : "") + c, "");

export function abilityGraphOption(root: AbilityHierarchyNode, view: AbilityView, reducedMotion = false): EChartsOption {
  const parents = new Map<string, number>();
  const decorate = (node: AbilityHierarchyNode): object => {
    node.children?.forEach((child) => parents.set(child.id, node.value));
    return { ...node, children: node.children?.map(decorate),
      itemStyle: { color: node.color, borderColor: "#fff", borderWidth: 1 },
    };
  };
  const tree = decorate(root) as AbilityHierarchyNode;
  const label = { show: true, fontSize: 12, lineHeight: 16,
    formatter: (p: { name: string }) => wrap(p.name) };
  const base = {
    backgroundColor: "#fff", animation: !reducedMotion,
    animationDuration: 450, animationDurationUpdate: 550,
    textStyle: { fontFamily: "Microsoft YaHei, PingFang SC, sans-serif" },
    tooltip: { trigger: "item", confine: true,
      extraCssText: "max-width:420px;white-space:normal;overflow-wrap:anywhere;",
      formatter: (parameters: unknown) => {
        const p = parameters as { data?: AbilityHierarchyNode; dataType?: string };
        const node = p.data;
        if (!node || p.dataType === "edge") return "父子关系";
        const parent = parents.get(node.id);
        const count = `${node.value} 项能力`;
        const share = node.kind !== "ability" && root.value ? ` · 占当前范围 ${(node.value / root.value * 100).toFixed(1)}%` : "";
        const parentShare = node.kind !== "ability" && parent ? ` · 占父级 ${(node.value / parent * 100).toFixed(1)}%` : "";
        return `${node.code ? `${escape(node.code)}<br/>` : ""}${escape(node.fullText).replace(/\n/g, "<br/>")}<br/>${count}${share}${parentShare}${node.flagged ? "<br/>来源编号或结构存在冲突，待核对" : ""}`;
      },
    },
  };
  if (view === "tree") return { ...base, series: [{
    type: "tree", data: [tree], orient: "LR", layout: "orthogonal", roam: true,
    top: 32, bottom: 32, left: 120, right: 230, symbolSize: 8, initialTreeDepth: -1,
    expandAndCollapse: true,
    label: { ...label, position: "left", align: "right", color: "#334155" },
    leaves: { label: { ...label, position: "right", align: "left" } },
    lineStyle: { color: ABILITY_COLORS.edge, width: 1.5, curveness: 0.35 },
    emphasis: { focus: "descendant" },
  }] } as EChartsOption;
  if (view === "sunburst") return { ...base, series: [{
    type: "sunburst", data: tree.children, radius: ["14%", "90%"], sort: null,
    nodeClick: "rootToNode", label: { ...label, rotate: "radial", minAngle: 0 },
    emphasis: { focus: "ancestor" },
    itemStyle: { borderColor: "#fff", borderWidth: 2 },
  }] } as EChartsOption;
  if (view === "treemap") return { ...base, series: [{
    type: "treemap", data: tree.children, sort: null, roam: false, nodeClick: "zoomToNode",
    visibleMin: 0, childrenVisibleMin: 0, top: 20, bottom: 46,
    label: { ...label, color: "#fff", overflow: "breakAll" },
    upperLabel: { show: true, height: 28, color: "#334155" },
    breadcrumb: { show: true, bottom: 8 },
    levels: [{ itemStyle: { borderWidth: 4, gapWidth: 4, borderColor: "#fff" } },
      { itemStyle: { borderWidth: 3, gapWidth: 3 } }, { itemStyle: { borderWidth: 1, gapWidth: 1 } }],
  }] } as EChartsOption;
  const flat = flattenAbilityHierarchy(root);
  return { ...base, series: [{
    type: "graph", layout: "force", roam: true, draggable: true,
    force: { repulsion: 180, edgeLength: [70, 140], gravity: 0.08, layoutAnimation: !reducedMotion },
    label: { ...label, position: "right", fontSize: 10 },
    lineStyle: { color: ABILITY_COLORS.edge, opacity: 0.8, width: 1.2 },
    emphasis: { focus: "adjacency" },
    data: flat.nodes.map((node) => ({ ...node, itemStyle: { color: node.color },
      symbolSize: node.kind === "root" ? 26 : node.kind === "task" ? 18 : node.kind === "ability" ? 7 : 12 })),
    links: flat.edges,
  }] } as EChartsOption;
}
