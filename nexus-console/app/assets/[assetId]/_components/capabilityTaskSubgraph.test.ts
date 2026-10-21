import { describe, expect, it } from "vitest";

import type { CapabilityGraphStagingEdge, CapabilityGraphStagingNode } from "@/lib/api";
import { abilityTaskSubgraphNodeIds } from "./capabilityTaskSubgraph";

const node = (id: string, type: string, sourceId: string) =>
  ({ id, node_type: type, source_id: sourceId }) as CapabilityGraphStagingNode;
const edge = (source: string, target: string) =>
  ({ source_node_id: source, target_node_id: target }) as CapabilityGraphStagingEdge;

describe("abilityTaskSubgraphNodeIds", () => {
  it("keeps only nodes reachable from the selected task", () => {
    const nodes = [
      node("task-1", "WorkTask", "source-1"),
      node("content-1", "WorkContent", "content-source-1"),
      node("ability-1", "Ability", "ability-source-1"),
      node("task-2", "WorkTask", "source-2"),
      node("ability-2", "Ability", "ability-source-2"),
    ];
    const edges = [edge("task-1", "content-1"), edge("content-1", "ability-1"), edge("task-2", "ability-2")];
    expect(abilityTaskSubgraphNodeIds(nodes, edges, "source-1")).toEqual(
      new Set(["task-1", "content-1", "ability-1"]),
    );
    expect(abilityTaskSubgraphNodeIds(nodes, edges, "missing")).toEqual(new Set());
  });
});
