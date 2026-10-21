import type { CapabilityGraphStagingEdge, CapabilityGraphStagingNode } from "@/lib/api";

export function abilityTaskSubgraphNodeIds(
  nodes: CapabilityGraphStagingNode[],
  edges: CapabilityGraphStagingEdge[],
  taskId: string,
): Set<string> {
  const root = nodes.find((node) => node.node_type === "WorkTask" && node.source_id === taskId);
  if (!root) return new Set();

  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    const targets = outgoing.get(edge.source_node_id) ?? [];
    targets.push(edge.target_node_id);
    outgoing.set(edge.source_node_id, targets);
  }
  const visited = new Set<string>([root.id]);
  const queue = [root.id];
  for (let index = 0; index < queue.length; index += 1) {
    for (const target of outgoing.get(queue[index]) ?? []) {
      if (!visited.has(target)) {
        visited.add(target);
        queue.push(target);
      }
    }
  }
  return visited;
}
