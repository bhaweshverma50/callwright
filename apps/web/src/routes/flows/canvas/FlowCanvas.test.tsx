import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { Flow, FlowGraph } from "../../../api/flows";
import { Toaster, TooltipProvider } from "../../../components";
import { useFlow } from "../hooks/useFlow";
import { mockNodeDefaults } from "../../../mocks/flows";
import { FlowCanvas, reconcileNodes, type NodeInputs, type Selection } from "./FlowCanvas";

const graph: FlowGraph = {
  nodes: [
    { id: "n_start000", type: "start", label: "Start", position: { x: 0, y: 0 }, config: mockNodeDefaults.start.config },
    { id: "n_agent000", type: "agent", label: "Triage", position: { x: 300, y: 0 }, config: mockNodeDefaults.agent.config },
    { id: "n_say00000", type: "say", label: "Say", position: { x: 600, y: 0 }, config: mockNodeDefaults.say.config },
  ],
  edges: [
    { id: "e_start000", source: "n_start000", target: "n_agent000", trigger: "always", sort_order: 0 },
    { id: "e_say00000", source: "n_agent000", target: "n_say00000", trigger: "llm_condition", label: "Say it", condition: "x", sort_order: 0 },
  ],
  viewport: { x: 0, y: 0, zoom: 1 },
};
const flow: Flow = {
  id: "flw_x",
  agent_id: "agt_x",
  name: "Clinic",
  graph,
  revision: 1,
  last_validation: { errors: 0, warnings: 0, issues: [] },
  created_at: "",
  updated_at: "",
};

let current: ReturnType<typeof useFlow> | null = null;

function Harness({ initial }: { initial: Selection }) {
  const draft = useFlow(flow);
  current = draft;
  const [selection, setSelection] = useState(initial);
  return (
    <TooltipProvider>
      <input aria-label="Some field" />
      <div style={{ width: 800, height: 600 }}>
        <FlowCanvas
          graph={draft.graph}
          setGraph={draft.setGraph}
          undo={draft.undo}
          redo={draft.redo}
          canUndo={draft.canUndo}
          canRedo={draft.canRedo}
          selection={selection}
          onSelect={setSelection}
          issues={[]}
          nodeDefaults={mockNodeDefaults}
        />
      </div>
      <Toaster />
    </TooltipProvider>
  );
}

describe("canvas keyboard and toolbar (T100)", () => {
  it("Delete removes the selected step and its connections as one undo step, with an Undo notice", () => {
    render(<Harness initial={{ nodes: ["n_say00000"], edges: [] }} />);
    act(() => void fireEvent.keyDown(window, { key: "Delete" }));
    expect(current!.graph.nodes.map((n) => n.id)).toEqual(["n_start000", "n_agent000"]);
    expect(current!.graph.edges.map((e) => e.id)).toEqual(["e_start000"]);
    const notice = screen.getByText("Deleted 1 step").closest("li")!;
    expect(within(notice).getByText("and 1 connection")).toBeInTheDocument();
    act(() => void fireEvent.click(within(notice).getByRole("button", { name: "Undo" })));
    expect(current!.graph).toEqual(graph);
  });

  it("Backspace while typing in a field never deletes the step", () => {
    render(<Harness initial={{ nodes: ["n_say00000"], edges: [] }} />);
    const field = screen.getByLabelText("Some field");
    field.focus();
    act(() => void fireEvent.keyDown(field, { key: "Backspace" }));
    expect(current!.graph.nodes).toHaveLength(3);
  });

  it("Backspace deletes a selected connection", () => {
    render(<Harness initial={{ nodes: [], edges: ["e_say00000"] }} />);
    act(() => void fireEvent.keyDown(window, { key: "Backspace" }));
    expect(current!.graph.edges.map((e) => e.id)).toEqual(["e_start000"]);
    expect(current!.graph.nodes).toHaveLength(3);
  });

  it("toolbar controls have accessible names", () => {
    render(<Harness initial={{ nodes: [], edges: [] }} />);
    const toolbar = screen.getByRole("toolbar", { name: "Canvas" });
    for (const name of ["Auto-layout", "Fit to screen", "Zoom in", "Zoom out", "Undo", "Redo"])
      expect(within(toolbar).getByRole("button", { name })).toBeInTheDocument();
  });

  it("Add step opens a grouped, labelled list; clicking a step adds and selects it", () => {
    render(<Harness initial={{ nodes: [], edges: [] }} />);
    expect(screen.queryByRole("button", { name: "Add Agent" })).not.toBeInTheDocument();
    act(() => void fireEvent.click(screen.getByRole("button", { name: "Add step" })));
    for (const group of ["Conversation", "Logic and data", "Call control"]) expect(screen.getByRole("region", { name: group })).toBeInTheDocument();
    for (const title of ["Agent", "Task", "Say", "Condition", "Extract", "API call", "Transfer", "End", "Start"])
      expect(screen.getByRole("button", { name: `Add ${title}` })).toHaveAttribute("draggable", "true");
    act(() => void fireEvent.click(screen.getByRole("button", { name: "Add Task" })));
    expect(current!.graph.nodes).toHaveLength(4);
    expect(current!.graph.nodes.at(-1)!.type).toBe("task");
  });
});

describe("canvas node reconcile (smooth drags)", () => {
  const base: NodeInputs = { nodes: graph.nodes, selected: [], locked: false, counts: {}, active: null, visited: new Set(), diff: undefined };

  it("moves only the node whose position changed", () => {
    const first = reconcileNodes([], base);
    const moved = graph.nodes.map((n) => (n.id === "n_say00000" ? { ...n, position: { x: 640, y: 20 } } : n));
    const next = reconcileNodes(first, { ...base, nodes: moved });
    expect(next.map((n) => n.position)).toEqual([graph.nodes[0]!.position, graph.nodes[1]!.position, { x: 640, y: 20 }]);
    expect(next.map((n) => n.data.node.label)).toEqual(["Start", "Triage", "Say"]);
  });

  it("selection marks the chosen node and keeps measured sizes", () => {
    const first = reconcileNodes([], base).map((n) => ({ ...n, measured: { width: 256, height: 100 } }));
    const next = reconcileNodes(first, { ...base, selected: ["n_agent000"] });
    expect(next.map((n) => n.selected)).toEqual([false, true, false]);
    expect(next.map((n) => n.measured)).toEqual(first.map(() => ({ width: 256, height: 100 })));
  });

  it("a node being dragged keeps its live position when the document changes underneath", () => {
    const first = reconcileNodes([], base).map((n) => (n.id === "n_agent000" ? { ...n, dragging: true, position: { x: 333, y: 44 } } : n));
    const next = reconcileNodes(first, { ...base, counts: { n_agent000: { errors: 1, warnings: 0 } } });
    expect(next[1]!.position).toEqual({ x: 333, y: 44 });
    expect(next[1]!.data.errors).toBe(1);
  });
});
