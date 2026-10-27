import { describe, expect, it } from "vitest";
import type { OccupationalAbilityItem, OccupationalWorkTask } from "@/lib/api";
import { ABILITY_COLORS, ABILITY_VIEWS, buildOccupationalHierarchy, flattenAbilityHierarchy, type AbilityHierarchyNode } from "./abilityHierarchy";
import { abilityGraphOption } from "./abilityGraphOptions";

export const tasks = [{ id: "t1", task_code: "1", task_name: "数据任务", display_order: 1,
  work_contents: [{ id: "w1", content_code: "1.1", content_name: "数据采集", display_order: 1 },
    { id: "w0", content_code: "1.2", content_name: "空内容", display_order: 2 }],
}, { id: "t2", task_code: "2", task_name: "第二任务", display_order: 2, work_contents: [] }] as OccupationalWorkTask[];
export const items = [
  { id: "p", task_id: "t1", work_content_id: "w1", ability_major_category_code: "P", ability_code: "P-1.1.1", ability_content: "能采集数据" },
  { id: "g1", task_id: "t1", work_content_id: null, ability_major_category_code: "G", ability_code: "G-1.1", ability_content: "能表达结果" },
  { id: "g2", task_id: "t1", work_content_id: null, ability_major_category_code: "G", ability_code: "G-1.1", ability_content: "能理解要求", quality_flags: { cross_sheet_inconsistency: true } },
  { id: "s", task_id: "t1", work_content_id: null, ability_major_category_code: "S", ability_code: "S-1.1", ability_content: "能协作" },
  { id: "d", task_id: "t2", work_content_id: null, ability_major_category_code: "D", ability_code: "D-2.1", ability_content: "能持续学习" },
] as unknown as OccupationalAbilityItem[];

describe("shared occupational hierarchy", () => {
  it("preserves duplicate source codes, correct parents and exact leaf weights without job categories", () => {
    const root = buildOccupationalHierarchy({ id: "a", major_name: "测试专业" }, tasks, items);
    const flat = flattenAbilityHierarchy(root);
    expect(root.value).toBe(5);
    expect(root.children?.map((n) => n.kind)).toEqual(["task", "task"]);
    expect(root.children?.[0].children?.map((n) => n.kind)).toEqual(["group", "group", "work", "work"]);
    expect(flat.nodes.find((n) => n.id === "work:w0")?.value).toBe(0);
    expect(flat.edges).toContainEqual({ source: "work:w1", target: "ability:p" });
    expect(flat.nodes.filter((n) => n.kind === "ability")).toHaveLength(5);
    expect(flat.nodes.find((n) => n.id === "ability:g2")?.flagged).toBe(true);
    expect(flat.edges).toHaveLength(flat.nodes.length - 1);
    expect(root.color).toBe("#025eff");
    expect(flat.nodes.find((n) => n.id === "ability:g1")?.color).toBe(ABILITY_COLORS.G);
  });

  it("uses identical business ids in all four options and exactly the shared tree edges in the graph", () => {
    expect(ABILITY_VIEWS.map((v) => v.label)).toEqual(["树图", "旭日图", "矩形树图", "关系图"]);
    const root = buildOccupationalHierarchy({ id: "a", major_name: "测试专业" }, tasks, items);
    const flat = flattenAbilityHierarchy(root);
    for (const view of ABILITY_VIEWS) {
      const option = abilityGraphOption(root, view.value, true) as { series: { type: string; data: AbilityHierarchyNode[]; links?: unknown[] }[] };
      expect(option.series[0].type).toBe(view.value);
      if (view.value === "graph") {
        expect(option.series[0].links).toEqual(flat.edges);
        expect(option.series[0].data.map((n) => n.id)).toEqual(flat.nodes.map((n) => n.id));
      } else {
        const ids = option.series[0].data.flatMap((node) => flattenAbilityHierarchy(node).nodes.map((n) => n.id));
        expect(new Set(ids)).toEqual(new Set(flat.nodes.filter((n) => view.value === "tree" || n.kind !== "root").map((n) => n.id)));
      }
    }
  });

  it("does not silently omit orphan abilities or unsafe tooltip text", () => {
    expect(() => buildOccupationalHierarchy({ id: "a", major_name: "测试专业" }, tasks, [...items, { ...items[0], id: "bad", task_id: "missing" }])).toThrow("缺少对应任务");
    const root = buildOccupationalHierarchy({ id: "a", major_name: "<script>" }, tasks, items);
    const option = abilityGraphOption(root, "tree") as { tooltip: { formatter: (p: unknown) => string } };
    expect(option.tooltip.formatter({ data: root })).toContain("&lt;script&gt;");
  });
});
