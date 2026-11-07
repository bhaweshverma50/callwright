import { useCallback, useMemo, useRef, useState } from "react";
import { FlowProblem, saveFlow, type AgentSettingsChange, type Flow, type FlowGraph } from "../../../api/flows";
import { useUndoRedo } from "../canvas/useUndoRedo";

export type SaveOutcome =
  | { status: "saved"; flow: Flow }
  | { status: "conflict"; code: "flow_revision_conflict" | "agent_draft_changed" }
  | { status: "invalid"; message: string }
  | { status: "error"; error: unknown };

function stable(v: unknown): string {
  return JSON.stringify(v, (_k, value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)))
      : value,
  );
}

/** Without positions or viewport: what makes a change worth saving. */
function content(graph: Pick<FlowGraph, "nodes" | "edges">): string {
  return stable({ nodes: graph.nodes, edges: graph.edges });
}

/** With positions but without the viewport: panning alone is not an unsaved change. */
function layout(graph: Pick<FlowGraph, "nodes" | "edges">): string {
  return stable({ nodes: graph.nodes, edges: graph.edges });
}

/**
 * The builder's draft (T021): the graph with undo and redo, the one name of flow and agent, the
 * flow-wide settings changed since loading, and a save that sends graph, name and settings in
 * one request with the loaded revisions (`If-Match` and `expected_draft_revision`).
 *
 * The viewport is kept out of React state: the canvas reports it after every pan, zoom or fit
 * (and many times a second while a drag auto-pans), and none of that should re-render the
 * builder. Saves send the latest one (FR-006).
 */
export function useFlow(initial: Flow) {
  const history = useUndoRedo<FlowGraph>(initial.graph);
  const [base, setBase] = useState(initial);
  const [name, setName] = useState(initial.name);
  const [saving, setSaving] = useState(false);
  const savedContent = useRef(content(initial.graph));
  const savedLayout = useRef(layout(initial.graph));
  const viewport = useRef(initial.graph.viewport);
  const setViewport = useCallback((vp: FlowGraph["viewport"]) => {
    viewport.current = vp;
  }, []);

  const graph = history.present;
  // Serialising the graph is the costly part of a dirty check; do it only when steps or
  // connections change (never for a pan or zoom, which only replaces the viewport).
  const { nodes, edges } = graph;
  const graphDirty = useMemo(() => layout({ nodes, edges }) !== savedLayout.current, [nodes, edges]);
  const meaningful = useMemo(() => content({ nodes, edges }) !== savedContent.current, [nodes, edges]);
  const nameDirty = name.trim() !== base.name;
  const dirty = graphDirty || nameDirty;

  /** Saves graph and name, plus `settings` (changed flow-wide settings) in the same request. */
  const save = useCallback(
    async (settings?: { changes: Record<string, unknown>; draftRevision: number }): Promise<SaveOutcome> => {
      setSaving(true);
      try {
        const change: AgentSettingsChange | undefined =
          settings && Object.keys(settings.changes).length
            ? { expected_draft_revision: settings.draftRevision, changes: settings.changes }
            : undefined;
        const saved = await saveFlow(base, name.trim(), { ...graph, viewport: viewport.current }, change);
        savedContent.current = content(saved.graph);
        savedLayout.current = layout(saved.graph);
        setBase(saved);
        // Keep the canvas as it is: the server's copy only differs in masked secrets.
        history.set(saved.graph, false);
        return { status: "saved", flow: saved };
      } catch (e) {
        if (e instanceof FlowProblem && e.status === 412)
          return { status: "conflict", code: e.code === "agent_draft_changed" ? "agent_draft_changed" : "flow_revision_conflict" };
        if (e instanceof FlowProblem && e.status === 422) return { status: "invalid", message: e.problem.detail ?? e.problem.title };
        return { status: "error", error: e };
      } finally {
        setSaving(false);
      }
    },
    [base, graph, history, name],
  );

  const resetTo = useCallback(
    (flow: Flow) => {
      savedContent.current = content(flow.graph);
      savedLayout.current = layout(flow.graph);
      setBase(flow);
      setName(flow.name);
      history.reset(flow.graph);
    },
    [history],
  );

  return {
    base,
    graph,
    setGraph: history.set,
    setViewport,
    undo: history.undo,
    redo: history.redo,
    canUndo: history.canUndo,
    canRedo: history.canRedo,
    name,
    setName,
    dirty,
    meaningful,
    saving,
    save,
    resetTo,
  };
}
