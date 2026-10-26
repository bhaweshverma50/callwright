import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Flow, FlowGraph } from "../../../api/flows";
import { TooltipProvider } from "../../../components";
import { useFlow } from "../hooks/useFlow";
import { defaultConfig } from "../model";
import { FlowCanvas, type Selection } from "./FlowCanvas";

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("../../../components/Toast", async (orig) => ({ ...(await orig<object>()), toast: toastSpy }));

const graph: FlowGraph = {
  nodes: [
    { id: "n_start000", type: "start", label: "Start", position: { x: 0, y: 0 }, config: defaultConfig("start") },
    { id: "n_agent000", type: "agent", label: "Triage", position: { x: 300, y: 0 }, config: defaultConfig("agent") },
    { id: "n_say00000", type: "say", label: "Say", position: { x: 600, y: 0 }, config: defaultConfig("say") },
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
          checkpoint={draft.checkpoint}
          undo={draft.undo}
          redo={draft.redo}
          canUndo={draft.canUndo}
          canRedo={draft.canRedo}
          selection={selection}
          onSelect={setSelection}
          issues={[]}
        />
      </div>
    </TooltipProvider>
  );
}

describe("canvas keyboard and toolbar (T100)", () => {
  it("Delete removes the selected step and its connections as one undo step, with an Undo notice", () => {
    render(<Harness initial={{ nodes: ["n_say00000"], edges: [] }} />);
    act(() => void fireEvent.keyDown(window, { key: "Delete" }));
    expect(current!.graph.nodes.map((n) => n.id)).toEqual(["n_start000", "n_agent000"]);
    expect(current!.graph.edges.map((e) => e.id)).toEqual(["e_start000"]);
    expect(toastSpy).toHaveBeenCalledWith(expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));
    act(() => current!.undo());
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
    for (const name of ["Auto-layout", "Fit to screen", "Zoom in", "Zoom out", "Undo", "Redo"])
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Agent" })).toBeInTheDocument();
  });
});
