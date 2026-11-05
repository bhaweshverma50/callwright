import { GitBranch } from "lucide-react";
import type { FlowTransition } from "../../api/calls";
import { Badge, cn } from "../../components";
import { mss } from "./format";

/**
 * Flow path of a flow-agent call (FR-013): every node visited in order with the transition taken.
 * Rendered only when the call has transitions (single-prompt calls have none).
 */
export function FlowPath({ items, highlight }: { items: FlowTransition[]; highlight?: Set<number> }) {
  if (items.length === 0) return null;
  const nodes = [{ id: items[0]!.from_node_id, label: items[0]!.from_label, seq: 0, edge: null as string | null, t: 0 }].concat(
    items.map((t) => ({ id: t.to_node_id, label: t.to_label, seq: t.seq, edge: t.edge_label ?? t.trigger, t: t.t_ms })),
  );
  return (
    <ol className="relative flex flex-col" aria-label="Flow path">
      {nodes.map((n, i) => {
        const last = i === nodes.length - 1;
        const differs = highlight?.has(n.seq);
        return (
          <li key={`${n.id}-${i}`} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && (
              <span aria-hidden className="absolute left-[11px] top-6 h-[calc(100%-20px)] w-px bg-gradient-to-b from-heat-1/60 to-heat-2/40" />
            )}
            <span
              aria-hidden
              className={cn(
                "relative mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-medium",
                last ? "bg-accent border-transparent text-white" : "border-line-strong bg-surface text-fg-2",
                differs && "border-transparent bg-warning-soft text-warning-text",
              )}
            >
              {i + 1}
            </span>
            <div className={cn("min-w-0 flex-1 rounded-control px-2 py-0.5", differs && "bg-warning-soft/50")}>
              <p className="flex flex-wrap items-center gap-2 text-[13px] text-fg">
                <span className="font-medium">{n.label || n.id}</span>
                {differs && <Badge tone="warning">Differs</Badge>}
                {i > 0 && <span className="font-mono text-[11px] text-fg-3 tnum">{mss(n.t / 1000)}</span>}
              </p>
              {n.edge && (
                <p className="mt-0.5 flex items-center gap-1.5 text-[12px] text-fg-3">
                  <GitBranch className="size-3" aria-hidden />
                  {n.edge}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
