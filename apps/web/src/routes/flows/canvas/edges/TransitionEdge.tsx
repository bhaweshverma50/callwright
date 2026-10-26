import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import { Check, CircleAlert, CornerDownRight, MessageSquareText, Tag, X } from "lucide-react";
import { memo, type ReactNode } from "react";
import type { FlowEdge } from "../../../../api/flows";
import type { DiffMark } from "../nodes/NodeCard";

export interface EdgeData extends Record<string, unknown> {
  edge: FlowEdge;
  errors: number;
  traversed: boolean;
  diff?: DiffMark;
}

export type CanvasEdge = Edge<EdgeData, "transition">;

const TRIGGER_ICON: Partial<Record<FlowEdge["trigger"], ReactNode>> = {
  llm_condition: <MessageSquareText aria-hidden />,
  category: <Tag aria-hidden />,
  rule: <CornerDownRight aria-hidden />,
  success: <Check aria-hidden />,
  failure: <X aria-hidden />,
};

/** What the edge pill says: the label the model sees, the category, the rule or the outcome. */
export function edgeText(e: FlowEdge): string | null {
  switch (e.trigger) {
    case "llm_condition":
      return e.label?.trim() || "Add a label";
    case "category":
      return e.category ?? "Choose a category";
    case "rule": {
      const r = e.rule;
      if (!r?.variable) return "Set the rule";
      return r.operator === "exists" ? `${r.variable} exists` : `${r.variable} ${OPS[r.operator] ?? r.operator} ${r.value ?? ""}`.trim();
    }
    case "else":
      return "Otherwise";
    case "success":
    case "failure":
    case "always":
      return null;
  }
}

const OPS: Record<string, string> = { equals: "=", not_equals: "≠", contains: "contains", matches: "matches", gt: ">", lt: "<" };

/**
 * A connection: a smooth step line with a closed arrow, and a pill at its middle with the label,
 * category or rule. Connections the model chooses read as the label it sees; a missing label is
 * shown in the warning colour so it is found before publishing.
 */
function TransitionEdgeImpl({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  markerEnd,
}: EdgeProps<CanvasEdge>) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 14,
    offset: 22,
  });
  const edge = data?.edge;
  const text = edge ? edgeText(edge) : null;
  const missing = edge?.trigger === "llm_condition" && !edge.label?.trim();
  const state = data?.diff ?? (data?.errors ? "error" : data?.traversed ? "traversed" : selected ? "selected" : undefined);
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} className="fedge" data-state={state} interactionWidth={22} />
      {text && edge && (
        <EdgeLabelRenderer>
          <div
            className="fedge-pill nodrag nopan"
            data-state={state}
            data-missing={missing || undefined}
            data-trigger={edge.trigger}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {data?.errors ? <CircleAlert aria-hidden /> : TRIGGER_ICON[edge.trigger]}
            <span className="truncate">{text}</span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const TransitionEdge = memo(TransitionEdgeImpl);
