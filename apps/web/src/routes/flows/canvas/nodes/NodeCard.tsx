import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { CircleAlert, TriangleAlert } from "lucide-react";
import { memo } from "react";
import type { FlowNode } from "../../../../api/flows";
import { cn } from "../../../../components";
import { outHandles } from "../../model";
import { NODE_META } from "../nodeMeta";

export type DiffMark = "added" | "removed" | "updated";

export interface NodeData extends Record<string, unknown> {
  node: FlowNode;
  summary: string;
  errors: number;
  warnings: number;
  /** The node a test call is in right now (FR-033). */
  active: boolean;
  visited: boolean;
  diff?: DiffMark;
}

export type CanvasNode = Node<NodeData>;

const DIFF_LABEL: Record<DiffMark, string> = { added: "New", removed: "Removed", updated: "Changed" };

/**
 * One node on the canvas: type chip, label, one-line summary and its handles. Nodes with one
 * outcome have a single handle on the right edge; nodes with several (categories, success and
 * failure, rule and otherwise) list them as rows, each with its handle on the card's edge.
 */
function NodeCardImpl({ data, selected }: NodeProps<CanvasNode>) {
  const { node, summary, errors, warnings, active, visited, diff } = data;
  const meta = NODE_META[node.type];
  const handles = outHandles(node);
  const rows = handles.length > 1 || (handles[0]?.label ?? null) !== null;
  return (
    <div
      className="fnode"
      data-ntype={node.type}
      data-selected={selected || undefined}
      data-active={active || undefined}
      data-visited={visited || undefined}
      data-diff={diff}
    >
      {node.type !== "start" && <Handle type="target" position={Position.Left} className="fnode-handle fnode-handle-in" />}
      <div className="flex items-start gap-2.5 px-3 pb-2 pt-3">
        <span className="fnode-chip" aria-hidden>
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-3">{meta.title}</p>
          <p className="truncate text-[13.5px] font-semibold leading-snug text-fg" title={node.label}>
            {node.label}
          </p>
        </div>
        {diff ? (
          <span className="fnode-diff">{DIFF_LABEL[diff]}</span>
        ) : errors > 0 ? (
          <span className="fnode-badge fnode-badge-error" title={`${errors} error${errors === 1 ? "" : "s"}`}>
            <CircleAlert aria-hidden />
            {errors}
          </span>
        ) : warnings > 0 ? (
          <span className="fnode-badge fnode-badge-warning" title={`${warnings} warning${warnings === 1 ? "" : "s"}`}>
            <TriangleAlert aria-hidden />
            {warnings}
          </span>
        ) : null}
      </div>
      <p className={cn("truncate px-3 text-[12px] leading-relaxed text-fg-2", rows ? "pb-2" : "pb-3")} title={summary}>
        {summary}
      </p>
      {rows ? (
        <div className="fnode-outs">
          {handles.map((h) => (
            <div key={h.id} className="fnode-out" data-tone={h.tone}>
              <span className="truncate">{h.label}</span>
              <Handle id={h.id} type="source" position={Position.Right} className="fnode-handle fnode-handle-out" />
            </div>
          ))}
        </div>
      ) : (
        handles[0] && <Handle id={handles[0].id} type="source" position={Position.Right} className="fnode-handle fnode-handle-out" />
      )}
    </div>
  );
}

export const NodeCard = memo(NodeCardImpl);
