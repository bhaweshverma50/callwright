import { describe, expect, it } from "vitest";
import type { FlowGraph, FlowNode } from "../../../api/flows";
import { mockNodeDefaults } from "../../../mocks/flows";
import { NODE_HEIGHT, NODE_WIDTH, autoLayout } from "./layout";

function bigGraph(count: number): FlowGraph {
  const nodes = Array.from({ length: count }, (_, i) => ({
    id: `n_${String(i).padStart(8, "0")}`,
    type: i === 0 ? "start" : "say",
    label: `Step ${i}`,
    position: { x: 0, y: 0 },
    config: mockNodeDefaults[i === 0 ? "start" : "say"].config,
  })) as FlowNode[];
  const edges = nodes.slice(1).map((n, i) => ({
    id: `e_${String(i).padStart(8, "0")}`,
    source: nodes[Math.floor(i / 3)]!.id,
    target: n.id,
    trigger: "always" as const,
    sort_order: 0,
  }));
  return { nodes, edges, viewport: { x: 0, y: 0, zoom: 1 } };
}

describe("autoLayout (T015)", () => {
  it("lays out 100 nodes left to right without overlaps in under a second", () => {
    const started = performance.now();
    const out = autoLayout(bigGraph(100));
    expect(performance.now() - started).toBeLessThan(1000);
    const boxes = out.nodes.map((n) => n.position);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i]!;
        const b = boxes[j]!;
        const overlap = a.x < b.x + NODE_WIDTH && b.x < a.x + NODE_WIDTH && a.y < b.y + NODE_HEIGHT && b.y < a.y + NODE_HEIGHT;
        expect(overlap).toBe(false);
      }
    const start = out.nodes[0]!.position.x;
    expect(out.nodes.slice(1).every((n) => n.position.x > start)).toBe(true);
  });
});
