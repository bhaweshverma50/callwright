import type { NodeProps } from "@xyflow/react";
import { NodeCard, type CanvasNode } from "./NodeCard";

/** Start node on the canvas; the shared card renders its handles from the node's outcomes. */
export function StartNode(props: NodeProps<CanvasNode>) {
  return <NodeCard {...props} />;
}
