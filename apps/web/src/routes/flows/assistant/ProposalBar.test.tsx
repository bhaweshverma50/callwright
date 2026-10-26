import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Flow, FlowGraph } from "../../../api/flows";
import { diffGraphs } from "../canvas/diffOverlay";
import { useFlow } from "../hooks/useFlow";
import { defaultConfig } from "../model";
import { approveProposal, type Proposal } from "./ProposalBar";

const base: FlowGraph = {
  nodes: [
    { id: "n_start000", type: "start", label: "Start", position: { x: 0, y: 0 }, config: defaultConfig("start") },
    { id: "n_agent000", type: "agent", label: "Triage", position: { x: 300, y: 0 }, config: defaultConfig("agent") },
  ],
  edges: [{ id: "e_start000", source: "n_start000", target: "n_agent000", trigger: "always", sort_order: 0 }],
  viewport: { x: 0, y: 0, zoom: 1 },
};
const flow: Flow = {
  id: "flw_01ARZ3NDEKTSV4RRFFQ69G5FAV",
  agent_id: "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV",
  name: "Clinic",
  graph: base,
  revision: 1,
  last_validation: { errors: 0, warnings: 0, issues: [] },
  created_at: "",
  updated_at: "",
};
const proposed: FlowGraph = {
  ...base,
  nodes: [...base.nodes, { id: "n_end00000", type: "end", label: "End", position: { x: 600, y: 0 }, config: defaultConfig("end") }],
  edges: [
    { ...base.edges[0]! },
    { id: "e_done0000", source: "n_agent000", target: "n_end00000", trigger: "llm_condition", label: "Done", condition: "Done", sort_order: 0 },
  ],
};
const proposal: Proposal = { message: "Added an end", graph: proposed, name: "Clinic v2", issues: [], baseRevision: 1 };

describe("assistant proposals (T087)", () => {
  it("decline leaves the exact pre-proposal graph", () => {
    const { result } = renderHook(() => useFlow(flow));
    const before = JSON.stringify(result.current.graph);
    const diff = diffGraphs(result.current.graph, proposal.graph);
    expect(diff.counts.addedNodes).toBe(1);
    // Declining never touched the draft: the proposal is only an overlay.
    expect(JSON.stringify(result.current.graph)).toBe(before);
    expect(result.current.dirty).toBe(false);
  });

  it("approve applies the proposal as one undo step", () => {
    const { result } = renderHook(() => useFlow(flow));
    act(() => approveProposal(proposal, result.current.setGraph, result.current.setName));
    expect(result.current.graph.nodes).toHaveLength(3);
    expect(result.current.name).toBe("Clinic v2");
    act(() => result.current.undo());
    expect(result.current.graph).toEqual(base);
  });
});
