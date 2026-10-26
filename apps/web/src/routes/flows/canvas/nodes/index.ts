import type { NodeTypes } from "@xyflow/react";
import { AgentNode } from "./AgentNode";
import { ConditionNode } from "./ConditionNode";
import { EndNode } from "./EndNode";
import { ExtractNode } from "./ExtractNode";
import { SayNode } from "./SayNode";
import { StartNode } from "./StartNode";
import { TaskNode } from "./TaskNode";
import { TransferNode } from "./TransferNode";
import { WebhookNode } from "./WebhookNode";

/** React Flow node types, keyed by the flow node type. */
export const nodeTypes: NodeTypes = {
  start: StartNode,
  agent: AgentNode,
  task: TaskNode,
  condition: ConditionNode,
  say: SayNode,
  extract_variable: ExtractNode,
  webhook: WebhookNode,
  transfer: TransferNode,
  end: EndNode,
};
