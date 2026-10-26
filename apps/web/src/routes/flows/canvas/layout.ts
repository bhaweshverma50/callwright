/**
 * Auto-layout (research R4): dagre, left to right in reading order, nodesep 60, ranksep 120,
 * margins 32, with each node's measured size so nothing overlaps.
 */
import dagre from "@dagrejs/dagre";
import type { FitViewOptions } from "@xyflow/react";
import type { FlowGraph } from "../../../api/flows";

export const NODE_WIDTH = 248;
export const NODE_HEIGHT = 104;

export type Sizes = Record<string, { width: number; height: number } | undefined>;

export function autoLayout(graph: FlowGraph, sizes: Sizes = {}): FlowGraph {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 96, marginx: 32, marginy: 32 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of graph.nodes) {
    const s = sizes[n.id];
    g.setNode(n.id, { width: s?.width ?? NODE_WIDTH, height: s?.height ?? NODE_HEIGHT });
  }
  const ids = new Set(graph.nodes.map((n) => n.id));
  for (const e of graph.edges) if (ids.has(e.source) && ids.has(e.target)) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return {
    ...graph,
    nodes: graph.nodes.map((n) => {
      const p = g.node(n.id);
      const s = sizes[n.id];
      const w = s?.width ?? NODE_WIDTH;
      const h = s?.height ?? NODE_HEIGHT;
      return { ...n, position: { x: Math.round(p.x - w / 2), y: Math.round(p.y - h / 2) } };
    }),
  };
}

/** Fit to screen: leaves room for the palette (left rail, or top row on phones) and the toolbar. */
export function fitOptions(width = typeof window === "undefined" ? 1440 : window.innerWidth): FitViewOptions {
  return width < 640
    ? { padding: { top: "76px", right: "16px", bottom: "80px", left: "16px" }, minZoom: 0.14, maxZoom: 1 }
    : { padding: { top: "36px", right: "56px", bottom: "84px", left: "92px" }, minZoom: 0.28, maxZoom: 1 };
}
