import type { FlowGraph } from "../../../api/flows";
import type { DiffMark } from "./nodes/NodeCard";

export interface GraphDiff {
  nodes: Record<string, DiffMark>;
  edges: Record<string, DiffMark>;
  /** Base and proposal together: removed items stay visible, struck through (FR-037). */
  shown: FlowGraph;
  counts: { addedNodes: number; removedNodes: number; updatedNodes: number; addedEdges: number; removedEdges: number; updatedEdges: number };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Diff styling for an assistant proposal (T090): green added, red removed, cobalt changed. */
export function diffGraphs(base: FlowGraph, proposed: FlowGraph): GraphDiff {
  const nodes: Record<string, DiffMark> = {};
  const edges: Record<string, DiffMark> = {};
  const baseNodes = new Map(base.nodes.map((n) => [n.id, n]));
  const nextNodes = new Map(proposed.nodes.map((n) => [n.id, n]));
  const baseEdges = new Map(base.edges.map((e) => [e.id, e]));
  const nextEdges = new Map(proposed.edges.map((e) => [e.id, e]));
  for (const n of proposed.nodes) {
    const was = baseNodes.get(n.id);
    if (!was) nodes[n.id] = "added";
    else if (was.label !== n.label || !same(was.config, n.config)) nodes[n.id] = "updated";
  }
  for (const n of base.nodes) if (!nextNodes.has(n.id)) nodes[n.id] = "removed";
  for (const e of proposed.edges) {
    const was = baseEdges.get(e.id);
    if (!was) edges[e.id] = "added";
    else if (!same(was, e)) edges[e.id] = "updated";
  }
  for (const e of base.edges) if (!nextEdges.has(e.id)) edges[e.id] = "removed";
  const shown: FlowGraph = {
    ...proposed,
    nodes: [...proposed.nodes, ...base.nodes.filter((n) => !nextNodes.has(n.id))],
    edges: [...proposed.edges, ...base.edges.filter((e) => !nextEdges.has(e.id))],
  };
  const count = (rec: Record<string, DiffMark>, mark: DiffMark) => Object.values(rec).filter((m) => m === mark).length;
  return {
    nodes,
    edges,
    shown,
    counts: {
      addedNodes: count(nodes, "added"),
      removedNodes: count(nodes, "removed"),
      updatedNodes: count(nodes, "updated"),
      addedEdges: count(edges, "added"),
      removedEdges: count(edges, "removed"),
      updatedEdges: count(edges, "updated"),
    },
  };
}
