/**
 * Flow graph model for the builder: node defaults (the same table as the API's starter.py),
 * fresh ids, how a connection's trigger follows from the handle it leaves, and graph edits.
 */
import type { ConfigByNode, FlowEdge, FlowGraph, FlowNode, NodeType, Trigger } from "../../api/flows";

const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";

export function shortId(prefix: "n" | "e", taken?: Set<string>): string {
  for (;;) {
    const bytes = crypto.getRandomValues(new Uint8Array(8));
    const id = `${prefix}_${Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join("")}`;
    if (!taken?.has(id)) return id;
  }
}

export const NODE_TYPES: NodeType[] = ["start", "agent", "task", "condition", "say", "extract_variable", "webhook", "transfer", "end"];
export const CONVERSATIONAL = new Set<NodeType>(["agent", "task"]);
/** The End node's old default line; the voice worker treats it like an empty message (the agent says its own goodbye). */
export const STOCK_END_MESSAGE = "Thanks for calling. Goodbye.";

export const DEFAULT_LABELS: Record<NodeType, string> = {
  start: "Start",
  agent: "Agent",
  task: "Collect details",
  condition: "Route",
  say: "Say",
  extract_variable: "Extract",
  webhook: "API call",
  transfer: "Transfer",
  end: "End",
};

const OVERRIDES = () => ({ llm: null, tts: null, stt: null, language: null });

export function defaultConfig<T extends NodeType>(type: T): ConfigByNode[T] {
  const table: { [K in NodeType]: () => ConfigByNode[K] } = {
    start: () => ({ start_speaker: "agent", greeting_type: "static", greeting: "Hi, thanks for calling. How can I help?" }),
    agent: () => ({
      instructions: "",
      begin_message: null,
      context_strategy: "inherit",
      overrides: OVERRIDES(),
      tool_ids: [],
      kb_search_enabled: true,
    }),
    task: () => ({
      instructions: "",
      begin_message: null,
      fields: [
        { name: "name", type: "string", description: "The caller's full name", required: true },
        { name: "email", type: "string", description: "The caller's email address", required: true },
      ],
      max_rounds: 5,
      context_strategy: "inherit",
      overrides: OVERRIDES(),
      tool_ids: [],
      kb_search_enabled: true,
    }),
    condition: () => ({
      kind: "classify",
      instructions: "",
      categories: [
        { name: "Sales", description: "The caller wants to buy something or asks about prices" },
        { name: "Support", description: "The caller needs help with something they already have" },
      ],
    }),
    say: () => ({ message: "", allow_interruptions: true }),
    extract_variable: () => ({ instructions: "", fields: [] }),
    webhook: () => ({
      request: {
        method: "POST",
        url: "",
        headers: [{ name: "Content-Type", value: "application/json", secret: false }],
        body_template: null,
        timeout_ms: 8000,
        response_mappings: [],
        speak_during_execution: true,
        execution_message: "One moment while I check that.",
      },
      mock_response: null,
    }),
    transfer: () => ({
      transfer: {
        routing_type: "static",
        number: "",
        allowed_numbers: [],
        transfer_type: "cold",
        warm_transfer: null,
        hold_message: "Please hold while I connect you.",
        ring_timeout_s: 30,
      },
    }),
    // Empty: the agent says a short goodbye in its own words that fits the call.
    end: () => ({ message: "", reason: "call_completed" }),
  };
  return table[type]() as ConfigByNode[T];
}

export function makeNode(type: NodeType, position: { x: number; y: number }, taken: Set<string>): FlowNode {
  return { id: shortId("n", taken), type, label: DEFAULT_LABELS[type], position, config: defaultConfig(type) } as FlowNode;
}

/** Output handles of a node: id, label and the trigger a connection from it gets. */
export interface OutHandle {
  id: string;
  label: string | null;
  trigger: Trigger;
  tone?: "success" | "danger" | "neutral";
}

export function outHandles(node: FlowNode): OutHandle[] {
  switch (node.type) {
    case "start":
    case "say":
    case "extract_variable":
      return [{ id: "out", label: null, trigger: "always" }];
    case "agent":
      return [{ id: "out", label: null, trigger: "llm_condition" }];
    case "task":
      return [
        { id: "success", label: "Collected", trigger: "success", tone: "success" },
        { id: "out", label: "Choice", trigger: "llm_condition" },
      ];
    case "condition": {
      const cfg = node.config as ConfigByNode["condition"];
      if (cfg.kind === "rule")
        return [
          { id: "rule", label: "Rule", trigger: "rule" },
          { id: "else", label: "Otherwise", trigger: "else", tone: "neutral" },
        ];
      return cfg.categories.map((c) => ({ id: `cat:${c.name}`, label: c.name, trigger: "category" as Trigger }));
    }
    case "webhook":
      return [
        { id: "success", label: "Success", trigger: "success", tone: "success" },
        { id: "failure", label: "Failure", trigger: "failure", tone: "danger" },
      ];
    case "transfer":
      return [{ id: "failure", label: "If it fails", trigger: "failure", tone: "danger" }];
    case "end":
      return [];
  }
}

/** The handle an existing edge leaves from (inverse of `outHandles`). */
export function handleOf(edge: FlowEdge): string {
  switch (edge.trigger) {
    case "category":
      return `cat:${edge.category ?? ""}`;
    case "success":
    case "failure":
    case "else":
    case "rule":
      return edge.trigger;
    default:
      return "out";
  }
}

export function newEdge(graph: FlowGraph, source: FlowNode, handleId: string | null, target: string): FlowEdge | null {
  const handle = outHandles(source).find((h) => h.id === (handleId ?? "out")) ?? outHandles(source)[0];
  if (!handle) return null;
  const siblings = graph.edges.filter((e) => e.source === source.id);
  const edge: FlowEdge = {
    id: shortId("e", new Set(graph.edges.map((e) => e.id))),
    source: source.id,
    target,
    trigger: handle.trigger,
    sort_order: siblings.length,
  };
  if (handle.trigger === "category") edge.category = handle.label;
  if (handle.trigger === "rule") edge.rule = { variable: "", operator: "equals", value: "" };
  if (handle.trigger === "llm_condition") {
    edge.label = "";
    edge.condition = "";
  }
  return edge;
}

/** Whether connecting this handle is allowed by the cardinality rules (data-model 2.2). */
export function canConnect(graph: FlowGraph, source: FlowNode, handleId: string | null, target: string): boolean {
  if (source.id === target) return false;
  const targetNode = graph.nodes.find((n) => n.id === target);
  if (!targetNode || targetNode.type === "start") return false;
  const handle = outHandles(source).find((h) => h.id === (handleId ?? "out"));
  if (!handle) return false;
  const existing = graph.edges.filter((e) => e.source === source.id && handleOf(e) === handle.id);
  const many = handle.trigger === "llm_condition" || handle.trigger === "rule";
  if (!many && existing.length >= 1) return false;
  return !graph.edges.some((e) => e.source === source.id && e.target === target && handleOf(e) === handle.id);
}

export function removeItems(graph: FlowGraph, nodeIds: Set<string>, edgeIds: Set<string>): FlowGraph {
  const removable = new Set(
    [...nodeIds].filter((id) => graph.nodes.find((n) => n.id === id)?.type !== "start" || graph.nodes.filter((n) => n.type === "start").length > 1),
  );
  return {
    ...graph,
    nodes: graph.nodes.filter((n) => !removable.has(n.id)),
    edges: graph.edges.filter((e) => !edgeIds.has(e.id) && !removable.has(e.source) && !removable.has(e.target)),
  };
}

export function duplicateNodes(graph: FlowGraph, ids: string[]): { graph: FlowGraph; created: string[] } {
  const taken = new Set(graph.nodes.map((n) => n.id));
  const created: string[] = [];
  const copies = graph.nodes
    .filter((n) => ids.includes(n.id) && n.type !== "start")
    .map((n) => {
      const id = shortId("n", taken);
      taken.add(id);
      created.push(id);
      return { ...structuredClone(n), id, label: `${n.label} copy`.slice(0, 80), position: { x: n.position.x + 40, y: n.position.y + 60 } };
    });
  return { graph: { ...graph, nodes: [...graph.nodes, ...copies] }, created };
}

/** Renaming a category carries its connections along (FR-043). */
export function renameCategory(graph: FlowGraph, nodeId: string, from: string, to: string): FlowEdge[] {
  return graph.edges.map((e) => (e.source === nodeId && e.trigger === "category" && e.category === from ? { ...e, category: to } : e));
}
