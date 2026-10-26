import {
  Background,
  BackgroundVariant,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type Viewport,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, type DragEvent } from "react";
import type { FlowGraph, NodeType, ValidationIssue } from "../../../api/flows";
import { toast } from "../../../components";
import { canConnect, duplicateNodes, makeNode, newEdge, removeItems } from "../model";
import { CanvasToolbar } from "./CanvasToolbar";
import { Palette } from "./Palette";
import { DRAG_TYPE } from "./nodeMeta";
import { TransitionEdge, type CanvasEdge } from "./edges/TransitionEdge";
import { fitOptions, autoLayout, type Sizes } from "./layout";
import { nodeTypes } from "./nodes";
import type { CanvasNode, DiffMark } from "./nodes/NodeCard";
import { nodeSummary } from "./nodes/NodeSummary";

export interface Selection {
  nodes: string[];
  edges: string[];
}
export const EMPTY_SELECTION: Selection = { nodes: [], edges: [] };

export interface CanvasProps {
  graph: FlowGraph;
  setGraph: (next: FlowGraph | ((g: FlowGraph) => FlowGraph), record?: boolean) => void;
  checkpoint: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  selection: Selection;
  onSelect: (s: Selection) => void;
  issues: ValidationIssue[];
  /** Live test call: the node the call is in and where it has been (FR-033). */
  activeNodeId?: string | null;
  visited?: Set<string>;
  /** Assistant proposal diff marks by node and edge id (FR-037). */
  diff?: { nodes: Record<string, DiffMark>; edges: Record<string, DiffMark> } | null;
  /** While a proposal is pending the canvas is read only. */
  locked?: boolean;
  onLockedAttempt?: () => void;
  modelLabel?: (provider: string, model: string) => string;
  /** Fit the whole graph once on mount (new canvases). */
  fitOnMount?: boolean;
  /** Bumped by the page to fit the view (after loading a proposal or a layout). */
  fitSignal?: number;
}

function isTyping(target: EventTarget | null) {
  if (!(target instanceof Element)) return false;
  const el = target as HTMLElement;
  return el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.closest("[role=dialog]") !== null;
}

const TYPES = { transition: TransitionEdge };

function Canvas(props: CanvasProps) {
  const { graph, setGraph, checkpoint, selection, onSelect, issues, locked, onLockedAttempt } = props;
  const flow = useReactFlow<CanvasNode, CanvasEdge>();
  const wrapper = useRef<HTMLDivElement>(null);

  const counts = useMemo(() => {
    const nodes: Record<string, { errors: number; warnings: number }> = {};
    const edges: Record<string, number> = {};
    for (const i of issues) {
      if (i.edge_id && i.severity === "error") edges[i.edge_id] = (edges[i.edge_id] ?? 0) + 1;
      if (i.node_id) {
        const c = (nodes[i.node_id] ??= { errors: 0, warnings: 0 });
        if (i.severity === "error") c.errors += 1;
        else c.warnings += 1;
      }
    }
    return { nodes, edges };
  }, [issues]);

  const traversed = useMemo(() => {
    const set = new Set<string>();
    if (!props.visited?.size) return set;
    for (const e of graph.edges) if (props.visited.has(e.source) && props.visited.has(e.target)) set.add(e.id);
    return set;
  }, [graph.edges, props.visited]);

  const nodes: CanvasNode[] = useMemo(() => {
    const selected = new Set(selection.nodes);
    return graph.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: n.position,
      selected: selected.has(n.id),
      draggable: !locked,
      data: {
        node: n,
        summary: nodeSummary(n, props.modelLabel),
        errors: counts.nodes[n.id]?.errors ?? 0,
        warnings: counts.nodes[n.id]?.warnings ?? 0,
        active: props.activeNodeId === n.id,
        visited: props.visited?.has(n.id) ?? false,
        diff: props.diff?.nodes[n.id],
      },
    }));
  }, [graph.nodes, selection.nodes, locked, counts, props.activeNodeId, props.visited, props.diff, props.modelLabel]);

  const edges: CanvasEdge[] = useMemo(() => {
    const selected = new Set(selection.edges);
    return graph.edges.map((e) => {
      const errors = counts.edges[e.id] ?? 0;
      const diff = props.diff?.edges[e.id];
      const isSelected = selected.has(e.id);
      const color = diff === "added" ? "var(--success)" : diff === "removed" ? "var(--danger)" : isSelected ? "var(--accent)" : "var(--text-3)";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: handleFor(e),
        type: "transition" as const,
        selected: isSelected,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color },
        data: { edge: e, errors, traversed: traversed.has(e.id), diff },
      };
    });
  }, [graph.edges, selection.edges, counts, traversed, props.diff]);

  // Selection arrives as separate node and edge changes; merge them into the latest selection.
  const current = useRef(selection);
  current.current = selection;
  const applySelect = useCallback(
    (kind: "nodes" | "edges", changes: { id: string; selected: boolean }[]) => {
      if (!changes.length) return;
      const set = new Set(current.current[kind]);
      for (const c of changes) {
        if (c.selected) set.add(c.id);
        else set.delete(c.id);
      }
      const next = { ...current.current, [kind]: [...set] };
      current.current = next;
      onSelect(next);
    },
    [onSelect],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      applySelect(
        "nodes",
        changes.flatMap((c) => (c.type === "select" ? [{ id: c.id, selected: c.selected }] : [])),
      );
      const moved = new Map<string, { x: number; y: number }>();
      for (const c of changes) if (c.type === "position" && c.position) moved.set(c.id, c.position);
      if (moved.size && !locked) {
        setGraph(
          (g) => ({
            ...g,
            nodes: g.nodes.map((n) => {
              const p = moved.get(n.id);
              return p ? { ...n, position: { x: Math.round(p.x), y: Math.round(p.y) } } : n;
            }),
          }),
          false,
        );
      }
    },
    [applySelect, locked, setGraph],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) =>
      applySelect(
        "edges",
        changes.flatMap((c) => (c.type === "select" ? [{ id: c.id, selected: c.selected }] : [])),
      ),
    [applySelect],
  );

  const isValidConnection = useCallback(
    (c: Connection | CanvasEdge) => {
      const source = graph.nodes.find((n) => n.id === c.source);
      return !locked && !!source && canConnect(graph, source, c.sourceHandle ?? null, c.target);
    },
    [graph, locked],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (locked) return onLockedAttempt?.();
      const source = graph.nodes.find((n) => n.id === c.source);
      if (!source || !canConnect(graph, source, c.sourceHandle ?? null, c.target)) return;
      const edge = newEdge(graph, source, c.sourceHandle ?? null, c.target);
      if (!edge) return;
      setGraph((g) => ({ ...g, edges: [...g.edges, edge] }));
      onSelect({ nodes: [], edges: [edge.id] });
    },
    [graph, locked, onLockedAttempt, onSelect, setGraph],
  );

  const addNode = useCallback(
    (type: NodeType, position?: { x: number; y: number }) => {
      if (locked) return onLockedAttempt?.();
      const box = wrapper.current?.getBoundingClientRect();
      const at =
        position ??
        flow.screenToFlowPosition({ x: (box?.left ?? 0) + (box?.width ?? 800) / 2 - 124, y: (box?.top ?? 0) + (box?.height ?? 600) / 2 - 52 });
      const node = makeNode(type, { x: Math.round(at.x), y: Math.round(at.y) }, new Set(graph.nodes.map((n) => n.id)));
      setGraph((g) => ({ ...g, nodes: [...g.nodes, node] }));
      onSelect({ nodes: [node.id], edges: [] });
    },
    [flow, graph.nodes, locked, onLockedAttempt, onSelect, setGraph],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      const type = e.dataTransfer.getData(DRAG_TYPE) as NodeType;
      if (!type) return;
      e.preventDefault();
      const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      addNode(type, { x: p.x - 124, y: p.y - 40 });
    },
    [addNode, flow],
  );

  const deleteSelection = useCallback(() => {
    if (locked) return onLockedAttempt?.();
    if (!selection.nodes.length && !selection.edges.length) return;
    const before = graph;
    const after = removeItems(graph, new Set(selection.nodes), new Set(selection.edges));
    if (after.nodes.length === before.nodes.length && after.edges.length === before.edges.length) return;
    setGraph(after);
    onSelect(EMPTY_SELECTION);
    const removedNodes = before.nodes.length - after.nodes.length;
    const removedEdges = before.edges.length - after.edges.length;
    toast({
      title: removedNodes
        ? `Deleted ${removedNodes} step${removedNodes === 1 ? "" : "s"}`
        : `Deleted ${removedEdges} connection${removedEdges === 1 ? "" : "s"}`,
      description: removedNodes && removedEdges ? `and ${removedEdges} connection${removedEdges === 1 ? "" : "s"}` : undefined,
      action: { label: "Undo", onClick: props.undo },
    });
  }, [graph, locked, onLockedAttempt, onSelect, props.undo, selection, setGraph]);

  const duplicate = useCallback(() => {
    if (locked) return onLockedAttempt?.();
    if (!selection.nodes.length) return;
    const { graph: next, created } = duplicateNodes(graph, selection.nodes);
    if (!created.length) return;
    setGraph(next);
    onSelect({ nodes: created, edges: [] });
  }, [graph, locked, onLockedAttempt, onSelect, selection.nodes, setGraph]);

  /** Keep the viewport in the draft after programmatic fits and zooms (FR-006). */
  const remember = useCallback(() => {
    const vp = flow.getViewport();
    setGraph((g) => ({ ...g, viewport: { x: Math.round(vp.x), y: Math.round(vp.y), zoom: Number(vp.zoom.toFixed(3)) } }), false);
  }, [flow, setGraph]);

  const layout = useCallback(() => {
    if (locked) return onLockedAttempt?.();
    const sizes: Sizes = {};
    for (const n of flow.getNodes()) sizes[n.id] = n.measured?.width ? { width: n.measured.width, height: n.measured.height ?? 104 } : undefined;
    setGraph((g) => autoLayout(g, sizes));
    window.setTimeout(() => void flow.fitView({ ...fitOptions(), duration: 360 }).then(remember), 40);
  }, [flow, locked, onLockedAttempt, remember, setGraph]);

  // Keyboard: Delete or Backspace removes the selection (never while typing), undo and redo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      const mod = e.metaKey || e.ctrlKey;
      if ((e.key === "Delete" || e.key === "Backspace") && !mod) {
        if (!selection.nodes.length && !selection.edges.length) return;
        e.preventDefault();
        deleteSelection();
      } else if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (locked) return onLockedAttempt?.();
        if (e.shiftKey) props.redo();
        else props.undo();
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        if (!locked) props.redo();
      } else if (mod && e.key.toLowerCase() === "d") {
        e.preventDefault();
        duplicate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelection, duplicate, locked, onLockedAttempt, props, selection]);

  useEffect(() => {
    if (props.fitSignal) void flow.fitView({ ...fitOptions(), duration: 360 }).then(remember);
  }, [flow, props.fitSignal, remember]);

  return (
    <div ref={wrapper} className="flow-canvas relative h-full w-full" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <ReactFlow<CanvasNode, CanvasEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onNodeDragStart={() => checkpoint()}
        onPaneClick={() => onSelect(EMPTY_SELECTION)}
        onMoveEnd={(_, vp: Viewport) =>
          setGraph((g) => ({ ...g, viewport: { x: Math.round(vp.x), y: Math.round(vp.y), zoom: Number(vp.zoom.toFixed(3)) } }), false)
        }
        defaultViewport={graph.viewport}
        fitView={props.fitOnMount}
        fitViewOptions={fitOptions()}
        onInit={() => props.fitOnMount && window.setTimeout(remember, 50)}
        minZoom={0.15}
        maxZoom={2}
        deleteKeyCode={null}
        multiSelectionKeyCode={["Meta", "Shift", "Control"]}
        selectionKeyCode="Shift"
        nodesConnectable={!locked}
        elementsSelectable
        connectionRadius={28}
        proOptions={{ hideAttribution: true }}
        aria-label="Flow canvas"
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} color="var(--dot)" />
      </ReactFlow>
      <Palette onAdd={addNode} disabled={locked} />
      <CanvasToolbar
        onLayout={layout}
        onViewChanged={remember}
        onUndo={() => (locked ? onLockedAttempt?.() : props.undo())}
        onRedo={() => (locked ? onLockedAttempt?.() : props.redo())}
        canUndo={props.canUndo && !locked}
        canRedo={props.canRedo && !locked}
      />
    </div>
  );
}

function handleFor(e: FlowGraph["edges"][number]): string {
  switch (e.trigger) {
    case "category":
      return `cat:${e.category ?? ""}`;
    case "success":
    case "failure":
    case "else":
    case "rule":
      return e.trigger;
    default:
      return "out";
  }
}

/** The flow canvas (T027, T101): connect, select, multi-select, delete, duplicate, pan, zoom. */
export function FlowCanvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
