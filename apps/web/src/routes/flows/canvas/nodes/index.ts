import type { NodeTypes } from "@xyflow/react";
import type { NodeType } from "../../../../api/flows";
import { NodeCard } from "./NodeCard";

/**
 * React Flow node types, keyed by the flow node type. Every type renders the one memoised card
 * (it draws its handles from the node's outcomes), and the map is a module constant so React Flow
 * never sees a new object.
 */
export const nodeTypes: NodeTypes = {
  start: NodeCard,
  agent: NodeCard,
  task: NodeCard,
  condition: NodeCard,
  say: NodeCard,
  extract_variable: NodeCard,
  webhook: NodeCard,
  transfer: NodeCard,
  end: NodeCard,
} satisfies Record<NodeType, NodeTypes[string]>;
