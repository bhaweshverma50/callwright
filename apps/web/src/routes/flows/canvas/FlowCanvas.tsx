import {
  Background,
  BackgroundVariant,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type OnNodeDrag,
  type Viewport,
} from "@xyflow/react";
import { memo, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import type { FlowGraph, FlowNode, NodeDefaults, NodeType, ValidationIssue } from "../../../api/flows";
import { toast } from "../../../components";
import { canConnect, duplicateNodes, makeNode, newEdge, removeItems } from "../model";
import { CanvasToolbar } from "./CanvasToolbar";
import { Palette } from "./Palette";
import { DRAG_TYPE } from "./nodeMeta";
import { TransitionEdge, type CanvasEdge, type EdgeData } from "./edges/TransitionEdge";
import { NODE_HEIGHT, NODE_WIDTH, fitOptions, autoLayout, type Sizes } from "./layout";
import { nodeTypes } from "./nodes";
import type { CanvasNode, DiffMark, NodeData } from "./nodes/NodeCard";
import { nodeSummary } from "./nodes/NodeSummary";

export interface Selection {
  nodes: string[];
  edges: string[];
}
export const EMPTY_SELECTION: Selection = { nodes: [], edges: [] };

export interface CanvasProps {
  graph: FlowGraph;
  setGraph: (next: FlowGraph | ((g: FlowGraph) => FlowGraph), record?: boolean) => void;
  /** The viewport after every pan, zoom or fit, kept for the next save (FR-006). */
  onViewport?: (viewport: Viewport) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  selection: Selection;
  onSelect: (s: Selection) => void;
  issues: ValidationIssue[];
  /** What a new node of each type starts with (from the API); steps cannot be added until it loads. */
  nodeDefaults?: NodeDefaults;
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

/** Stable outside the component, so React Flow never sees a new edge type map (xyflow warns and remounts). */
const EDGE_TYPES = { transition: TransitionEdge };
const EMPTY_VISITED = new Set<string>();

export interface NodeInputs {
  nodes: FlowNode[];
  selected: string[];
  locked: boolean;
  counts: Record<string, { errors: number; warnings: number }>;
  active: string | null;
  visited: Set<string>;
  diff: Record<string, DiffMark> | undefined;
  modelLabel?: (provider: string, model: string) => string;
}

function sameData(a: NodeData, b: NodeData) {
  return (
    a.node === b.node &&
    a.summary === b.summary &&
    a.errors === b.errors &&
    a.warnings === b.warnings &&
    a.active === b.active &&
    a.visited === b.visited &&
    a.diff === b.diff
  );
}

/**
 * Brings the canvas nodes in line with the document. Nodes whose step, flags and position did not
 * change keep their object (so React Flow and the memoised cards skip them), measured sizes are
 * carried over (so handles are not re-measured), and a node being dragged keeps its live position.
 */
export function reconcileNodes(current: CanvasNode[], input: NodeInputs): CanvasNode[] {
  const byId = new Map(current.map((n) => [n.id, n]));
  const selected = new Set(input.selected);
  let changed = current.length !== input.nodes.length;
  const out = input.nodes.map((n, i) => {
    const old = byId.get(n.id);
    const c = input.counts[n.id];
    const fresh: NodeData = {
      node: n,
      summary: old?.data.node === n ? old.data.summary : nodeSummary(n, input.modelLabel),
      errors: c?.errors ?? 0,
      warnings: c?.warnings ?? 0,
      active: input.active === n.id,
      visited: input.visited.has(n.id),
      diff: input.diff?.[n.id],
    };
    const data = old && sameData(old.data, fresh) ? old.data : fresh;
    const isSelected = selected.has(n.id);
    const position = old?.dragging ? old.position : n.position;
    if (
      old &&
      old.data === data &&
      old.selected === isSelected &&
      old.draggable === !input.locked &&
      old.position.x === position.x &&
      old.position.y === position.y
    ) {
      if (current[i] !== old) changed = true;
      return old;
    }
    changed = true;
    return { ...old, id: n.id, type: n.type, position, selected: isSelected, draggable: !input.locked, data } as CanvasNode;
  });
  return changed ? out : current;
}

function Canvas(props: CanvasProps) {
  const { graph, setGraph, onViewport, selection, onSelect, issues, nodeDefaults, locked = false, onLockedAttempt, modelLabel, undo, redo } = props;
  const flow = useReactFlow<CanvasNode, CanvasEdge>();
  const wrapper = useRef<HTMLDivElement>(null);
  // Callbacks read the latest graph through a ref, so they keep one identity and React Flow
  // never re-renders its internals because a handler changed.
  const graphRef = useRef(graph);
  graphRef.current = graph;

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

  const visited = props.visited ?? EMPTY_VISITED;
  const traversed = useMemo(() => {
    const set = new Set<string>();
    if (!visited.size) return set;
    for (const e of graph.edges) if (visited.has(e.source) && visited.has(e.target)) set.add(e.id);
    return set;
  }, [graph.edges, visited]);

  // Nodes live in local state while they move: a drag only touches this state (applyNodeChanges),
  // and the document is updated once, on drag stop. Everything else flows from the document.
  const inputs: NodeInputs = useMemo(
    () => ({
      nodes: graph.nodes,
      selected: selection.nodes,
      locked,
      counts: counts.nodes,
      active: props.activeNodeId ?? null,
      visited,
      diff: props.diff?.nodes,
      modelLabel,
    }),
    [graph.nodes, selection.nodes, locked, counts.nodes, props.activeNodeId, visited, props.diff?.nodes, modelLabel],
  );
  const [nodes, setNodes] = useState<CanvasNode[]>(() => reconcileNodes([], inputs));
  const [synced, setSynced] = useState(inputs);
  if (synced !== inputs) {
    setSynced(inputs);
    setNodes((cur) => reconcileNodes(cur, inputs));
  }

  const edgeCache = useRef(new Map<string, CanvasEdge>());
  const edges: CanvasEdge[] = useMemo(() => {
    const selected = new Set(selection.edges);
    const next = new Map<string, CanvasEdge>();
    const out = graph.edges.map((e) => {
      const errors = counts.edges[e.id] ?? 0;
      const diff = props.diff?.edges[e.id];
      const isSelected = selected.has(e.id);
      const isTraversed = traversed.has(e.id);
      const old = edgeCache.current.get(e.id);
      const d = old?.data;
      if (old && d && d.edge === e && d.errors === errors && d.diff === diff && d.traversed === isTraversed && old.selected === isSelected) {
        next.set(e.id, old);
        return old;
      }
      const color = diff === "added" ? "var(--success)" : diff === "removed" ? "var(--danger)" : isSelected ? "var(--accent)" : "var(--text-3)";
      const data: EdgeData = { edge: e, errors, traversed: isTraversed, diff };
      const edge: CanvasEdge = {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: handleFor(e),
        type: "transition",
        selected: isSelected,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color },
        data,
      };
      next.set(e.id, edge);
      return edge;
    });
    edgeCache.current = next;
    return out;
  }, [graph.edges, selection.edges, counts.edges, traversed, props.diff?.edges]);

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
      if (next[kind].length === current.current[kind].length && next[kind].every((id, i) => current.current[kind][i] === id)) return;
      current.current = next;
      onSelect(next);
    },
    [onSelect],
  );

  // Picking up a step that is not selected makes React Flow clear the selection first (so the
  // old selection does not move along). That would close or switch the settings panel mid-drag,
  // so a batch that only deselects waits a microtask: if a drag started in the same tick (React
  // Flow calls onNodeDragStart right after), it is dropped and the panel keeps what it shows.
  const pending = useRef<{ nodes: string[]; edges: string[] } | null>(null);
  const dragStarting = useRef(false);
  const select = useCallback(
    (kind: "nodes" | "edges", changes: { id: string; selected: boolean }[]) => {
      if (!changes.length) return;
      if (changes.some((c) => c.selected)) return applySelect(kind, changes);
      if (!pending.current) {
        pending.current = { nodes: [], edges: [] };
        dragStarting.current = false;
        queueMicrotask(() => {
          const p = pending.current;
          pending.current = null;
          if (!p || dragStarting.current) return;
          applySelect(
            "nodes",
            p.nodes.map((id) => ({ id, selected: false })),
          );
          applySelect(
            "edges",
            p.edges.map((id) => ({ id, selected: false })),
          );
        });
      }
      pending.current[kind].push(...changes.map((c) => c.id));
    },
    [applySelect],
  );
  const onNodeDragStart = useCallback(() => {
    dragStarting.current = true;
  }, []);

  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      const selects: { id: string; selected: boolean }[] = [];
      const local: NodeChange<CanvasNode>[] = [];
      for (const c of changes) {
        if (c.type === "select") selects.push({ id: c.id, selected: c.selected });
        else if (c.type === "position" || c.type === "dimensions") local.push(c);
      }
      if (local.length) setNodes((ns) => applyNodeChanges(local, ns));
      select("nodes", selects);
    },
    [select],
  );

  /** One write to the document per drag, recorded as one undo step. */
  const onNodeDragStop: OnNodeDrag<CanvasNode> = useCallback(
    (_e, _node, dragged) => {
      // React Flow quietly unselected its copy of the kept selection when the drag began; hand
      // it fresh objects so its selection matches the panel again.
      setNodes((ns) => (ns.some((n) => n.selected) ? ns.map((n) => (n.selected ? { ...n } : n)) : ns));
      if (locked) return;
      const moved = new Map(dragged.map((n) => [n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) }]));
      setGraph((g) => {
        let any = false;
        const nodes = g.nodes.map((n) => {
          const p = moved.get(n.id);
          if (!p || (p.x === n.position.x && p.y === n.position.y)) return n;
          any = true;
          return { ...n, position: p };
        });
        return any ? { ...g, nodes } : g;
      });
    },
    [locked, setGraph],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) =>
      select(
        "edges",
        changes.flatMap((c) => (c.type === "select" ? [{ id: c.id, selected: c.selected }] : [])),
      ),
    [select],
  );

  const isValidConnection = useCallback(
    (c: Connection | CanvasEdge) => {
      const g = graphRef.current;
      const source = g.nodes.find((n) => n.id === c.source);
      return !locked && !!source && canConnect(g, source, c.sourceHandle ?? null, c.target);
    },
    [locked],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (locked) return onLockedAttempt?.();
      const g = graphRef.current;
      const source = g.nodes.find((n) => n.id === c.source);
      if (!source || !canConnect(g, source, c.sourceHandle ?? null, c.target)) return;
      const edge = newEdge(g, source, c.sourceHandle ?? null, c.target);
      if (!edge) return;
      setGraph((x) => ({ ...x, edges: [...x.edges, edge] }));
      onSelect({ nodes: [], edges: [edge.id] });
    },
    [locked, onLockedAttempt, onSelect, setGraph],
  );

  const addNode = useCallback(
    (type: NodeType, position?: { x: number; y: number }) => {
      if (locked) return onLockedAttempt?.();
      if (!nodeDefaults) return;
      const box = wrapper.current?.getBoundingClientRect();
      const at =
        position ??
        flow.screenToFlowPosition({
          x: (box?.left ?? 0) + (box?.width ?? 800) / 2 - NODE_WIDTH / 2,
          y: (box?.top ?? 0) + (box?.height ?? 600) / 2 - NODE_HEIGHT / 2,
        });
      const node = makeNode(type, { x: Math.round(at.x), y: Math.round(at.y) }, new Set(graphRef.current.nodes.map((n) => n.id)), nodeDefaults[type]);
      setGraph((g) => ({ ...g, nodes: [...g.nodes, node] }));
      onSelect({ nodes: [node.id], edges: [] });
    },
    [flow, locked, nodeDefaults, onLockedAttempt, onSelect, setGraph],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      const type = e.dataTransfer.getData(DRAG_TYPE) as NodeType;
      if (!type) return;
      e.preventDefault();
      const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      addNode(type, { x: p.x - NODE_WIDTH / 2, y: p.y - 40 });
    },
    [addNode, flow],
  );

  const deleteSelection = useCallback(() => {
    if (locked) return onLockedAttempt?.();
    const sel = current.current;
    if (!sel.nodes.length && !sel.edges.length) return;
    const before = graphRef.current;
    const after = removeItems(before, new Set(sel.nodes), new Set(sel.edges));
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
      action: { label: "Undo", onClick: undo },
    });
  }, [locked, onLockedAttempt, onSelect, undo, setGraph]);

  const duplicate = useCallback(() => {
    if (locked) return onLockedAttempt?.();
    const sel = current.current;
    if (!sel.nodes.length) return;
    const { graph: next, created } = duplicateNodes(graphRef.current, sel.nodes);
    if (!created.length) return;
    setGraph(next);
    onSelect({ nodes: created, edges: [] });
  }, [locked, onLockedAttempt, onSelect, setGraph]);

  /** Keep the viewport in the draft after programmatic fits and zooms (FR-006). */
  const keepViewport = useCallback(
    (vp: Viewport) => onViewport?.({ x: Math.round(vp.x), y: Math.round(vp.y), zoom: Number(vp.zoom.toFixed(3)) }),
    [onViewport],
  );
  const remember = useCallback(() => keepViewport(flow.getViewport()), [flow, keepViewport]);
  const onMoveEnd = useCallback((_: unknown, vp: Viewport) => keepViewport(vp), [keepViewport]);

  const layout = useCallback(() => {
    if (locked) return onLockedAttempt?.();
    const sizes: Sizes = {};
    for (const n of flow.getNodes())
      sizes[n.id] = n.measured?.width ? { width: n.measured.width, height: n.measured.height ?? NODE_HEIGHT } : undefined;
    setGraph((g) => autoLayout(g, sizes));
    window.setTimeout(() => void flow.fitView({ ...fitOptions(), duration: 360 }).then(remember), 40);
  }, [flow, locked, onLockedAttempt, remember, setGraph]);

  const keys = useRef({ deleteSelection, duplicate, locked, onLockedAttempt, undo, redo });
  keys.current = { deleteSelection, duplicate, locked, onLockedAttempt, undo, redo };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      const k = keys.current;
      const mod = e.metaKey || e.ctrlKey;
      if ((e.key === "Delete" || e.key === "Backspace") && !mod) {
        if (!current.current.nodes.length && !current.current.edges.length) return;
        e.preventDefault();
        k.deleteSelection();
      } else if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (k.locked) return k.onLockedAttempt?.();
        if (e.shiftKey) k.redo();
        else k.undo();
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        if (!k.locked) k.redo();
      } else if (mod && e.key.toLowerCase() === "d") {
        e.preventDefault();
        k.duplicate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (props.fitSignal) void flow.fitView({ ...fitOptions(), duration: 360 }).then(remember);
  }, [flow, props.fitSignal, remember]);

  const onPaneClick = useCallback(() => onSelect(EMPTY_SELECTION), [onSelect]);
  const fitOnMount = props.fitOnMount;
  const onInit = useCallback(() => {
    if (fitOnMount) window.setTimeout(remember, 50);
  }, [fitOnMount, remember]);
  const onUndo = useCallback(() => (locked ? onLockedAttempt?.() : undo()), [locked, onLockedAttempt, undo]);
  const onRedo = useCallback(() => (locked ? onLockedAttempt?.() : redo()), [locked, onLockedAttempt, redo]);
  // React Flow reads these once; keeping them stable avoids needless store updates.
  const [defaultViewport] = useState(graph.viewport);
  const [fitViewOptions] = useState(() => fitOptions());

  return (
    <div ref={wrapper} className="flow-canvas relative h-full w-full" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <ReactFlow<CanvasNode, CanvasEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStart={onNodeDragStart}
        onNodeDragStop={onNodeDragStop}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onPaneClick={onPaneClick}
        onMoveEnd={onMoveEnd}
        defaultViewport={defaultViewport}
        fitView={fitOnMount}
        fitViewOptions={fitViewOptions}
        onInit={onInit}
        minZoom={0.15}
        maxZoom={2}
        deleteKeyCode={null}
        multiSelectionKeyCode={MULTI_KEYS}
        selectionKeyCode="Shift"
        selectNodesOnDrag={false}
        nodesConnectable={!locked}
        elementsSelectable
        connectionRadius={28}
        proOptions={PRO_OPTIONS}
        aria-label="Flow canvas"
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.3} color="var(--dot)" />
      </ReactFlow>
      <Palette onAdd={addNode} disabled={locked || !nodeDefaults} />
      <CanvasToolbar
        onLayout={layout}
        onViewChanged={remember}
        onUndo={onUndo}
        onRedo={onRedo}
        canUndo={props.canUndo && !locked}
        canRedo={props.canRedo && !locked}
      />
    </div>
  );
}

const MULTI_KEYS = ["Meta", "Shift", "Control"];
const PRO_OPTIONS = { hideAttribution: true };

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

/**
 * The flow canvas (T027, T101): connect, select, multi-select, delete, duplicate, pan, zoom.
 * Memoised: the builder re-renders for many reasons (typing in a panel, a tab change) that leave
 * the canvas props as they were.
 */
export const FlowCanvas = memo(function FlowCanvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
});
