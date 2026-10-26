import type { NodeProps } from "@xyflow/react";
import { NodeCard, type CanvasNode } from "./NodeCard";

/** Webhook node on the canvas; the shared card renders its handles from the node's outcomes. */
export function WebhookNode(props: NodeProps<CanvasNode>) {
  return <NodeCard {...props} />;
}
