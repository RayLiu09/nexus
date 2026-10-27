import type { AbilityAnalysis, OccupationalAbilityItem, OccupationalWorkTask } from "@/lib/api";

export const ABILITY_COLORS = {
  P: "#2563eb", G: "#7c3aed", S: "#0d9488", D: "#0891b2",
  task: "#94a3b8", edge: "#bfdbfe", root: "#025eff",
  jobClass: ["#6366f1", "#0ea5e9", "#f59e0b", "#ec4899", "#22c55e", "#eab308"],
} as const;
export const ABILITY_VIEWS = [
  { label: "树图", value: "tree" },
  { label: "旭日图", value: "sunburst" },
  { label: "矩形树图", value: "treemap" },
  { label: "关系图", value: "graph" },
] as const;
export type AbilityView = typeof ABILITY_VIEWS[number]["value"];
export type AbilityHierarchyNode = {
  id: string;
  name: string;
  fullText: string;
  kind: "root" | "task" | "group" | "work" | "ability";
  color: string;
  value: number;
  sourceId?: string;
  code?: string;
  flagged?: boolean;
  children?: AbilityHierarchyNode[];
};

const labels: Record<string, string> = { P: "职业能力", G: "通用能力", S: "社会能力", D: "发展能力" };
const compare = (a: string, b: string) => a.localeCompare(b, "zh-CN", { numeric: true });
const shortName = (text: string) => text.length > 18 ? `${text.slice(0, 18)}…` : text;

function branch(node: Omit<AbilityHierarchyNode, "value">): AbilityHierarchyNode {
  return { ...node, value: (node.children ?? []).reduce((sum, child) => sum + child.value, 0) };
}

export function buildOccupationalHierarchy(
  analysis: Pick<AbilityAnalysis, "id" | "major_name">,
  tasks: OccupationalWorkTask[],
  abilities: OccupationalAbilityItem[],
): AbilityHierarchyNode {
  const ids = new Set<string>();
  for (const ability of abilities) {
    if (ids.has(ability.id)) throw new Error("能力数据包含重复记录，请重新加载");
    ids.add(ability.id);
  }
  const taskIds = new Set(tasks.map((task) => task.id));
  if (abilities.some((item) => !taskIds.has(item.task_id))) {
    throw new Error("部分能力缺少对应任务，请先修复源数据");
  }
  const leaf = (ability: OccupationalAbilityItem): AbilityHierarchyNode => ({
    id: `ability:${ability.id}`, sourceId: ability.id, kind: "ability",
    name: shortName(ability.ability_content || ability.ability_code),
    fullText: ability.ability_content, code: ability.ability_code, value: 1,
    color: ABILITY_COLORS[ability.ability_major_category_code as "P"] ?? ABILITY_COLORS.task,
    flagged: Object.values(ability.quality_flags ?? {}).some(Boolean),
  });
  const taskNodes = [...tasks].sort((a, b) => a.display_order - b.display_order || compare(a.task_code, b.task_code)).map((task) => {
    const items = abilities.filter((a) => a.task_id === task.id).sort((a, b) => compare(a.ability_code, b.ability_code) || compare(a.id, b.id));
    const children: AbilityHierarchyNode[] = [];
    for (const category of ["G", "S", "D"]) {
      const group = items.filter((a) => a.ability_major_category_code === category);
      if (group.length) children.push(branch({
        id: `task:${task.id}:group:${category}`, name: labels[category], fullText: labels[category],
        kind: "group", color: ABILITY_COLORS[category as "G"], children: group.map(leaf),
      }));
    }
    const contents = [...(task.work_contents ?? [])].sort((a, b) => a.display_order - b.display_order || compare(a.content_code, b.content_code));
    const contentIds = new Set(contents.map((w) => w.id));
    const pItems = items.filter((a) => a.ability_major_category_code === "P");
    if (pItems.some((a) => !a.work_content_id || !contentIds.has(a.work_content_id))) {
      throw new Error("部分职业能力缺少对应工作内容，请先修复源数据");
    }
    for (const content of contents) children.push(branch({
      id: `work:${content.id}`, sourceId: content.id, kind: "work", code: content.content_code,
      name: shortName(content.content_name), fullText: content.content_name,
      color: ABILITY_COLORS.P, children: pItems.filter((a) => a.work_content_id === content.id).map(leaf),
    }));
    if (items.some((a) => !["P", "G", "S", "D"].includes(a.ability_major_category_code))) {
      throw new Error("存在未识别的能力类别，请先核对源数据");
    }
    return branch({ id: `task:${task.id}`, sourceId: task.id, kind: "task", code: task.task_code,
      name: shortName(task.task_name), fullText: [task.task_name, task.task_description].filter(Boolean).join("\n\n"),
      color: ABILITY_COLORS.task, children });
  });
  return branch({ id: `analysis:${analysis.id}`, kind: "root", name: analysis.major_name || "职业能力分析",
    fullText: analysis.major_name || "职业能力分析", color: ABILITY_COLORS.root, children: taskNodes });
}

export function flattenAbilityHierarchy(root: AbilityHierarchyNode) {
  const nodes: AbilityHierarchyNode[] = [];
  const edges: { source: string; target: string }[] = [];
  const visit = (node: AbilityHierarchyNode, parent?: AbilityHierarchyNode) => {
    nodes.push(node);
    if (parent) edges.push({ source: parent.id, target: node.id });
    node.children?.forEach((child) => visit(child, node));
  };
  visit(root);
  return { nodes, edges };
}
