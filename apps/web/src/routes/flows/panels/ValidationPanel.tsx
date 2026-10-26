import { CircleAlert, CircleCheck, Trash2, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { FlowGraph, FlowValidationResult, ValidationIssue } from "../../../api/flows";
import { Button, Skeleton, cn, focusRing } from "../../../components";

/**
 * Problems (T044, FR-024): errors block publishing, warnings inform. Clicking one selects the
 * node or connection at fault; a dangling connection can be removed right here.
 */
export function ValidationPanel({
  result,
  graph,
  checking,
  onPick,
  onRemoveEdge,
}: {
  result: FlowValidationResult | null;
  graph: FlowGraph;
  checking: boolean;
  onPick: (issue: ValidationIssue) => void;
  onRemoveEdge: (edgeId: string) => void;
}) {
  if (!result) return <Skeleton className="m-5 h-24" />;
  const labelOf = (i: ValidationIssue) => {
    if (i.node_id) return graph.nodes.find((n) => n.id === i.node_id)?.label ?? "Missing step";
    if (i.edge_id) {
      const e = graph.edges.find((x) => x.id === i.edge_id);
      const from = graph.nodes.find((n) => n.id === e?.source)?.label;
      const to = graph.nodes.find((n) => n.id === e?.target)?.label;
      return `${from ?? "?"} to ${to ?? "?"}`;
    }
    return "Flow";
  };
  return (
    <div className="flex flex-col gap-3 px-5 py-4">
      <p className="flex items-center gap-2 text-[12.5px] text-fg-3" aria-live="polite">
        {result.errors === 0 && result.warnings === 0 ? (
          <>
            <CircleCheck className="size-4 text-success" aria-hidden /> No problems. Ready to publish.
          </>
        ) : (
          <>
            <span className="font-medium text-fg">
              {result.errors} error{result.errors === 1 ? "" : "s"}, {result.warnings} warning{result.warnings === 1 ? "" : "s"}
            </span>
            {result.errors > 0 && <span>Errors block publishing.</span>}
          </>
        )}
        {checking && <span className="ml-auto size-1.5 animate-pulse rounded-full bg-accent" aria-label="Checking" />}
      </p>
      <ul className="flex flex-col gap-1.5">
        <AnimatePresence initial={false}>
          {result.issues.map((i, k) => (
            <motion.li
              key={`${i.code}-${i.node_id}-${i.edge_id}-${i.field}-${k}`}
              layout
              initial={{ opacity: 0, y: -3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <div
                className={cn(
                  "group flex items-start gap-2.5 rounded-control border px-3 py-2.5 transition-[background-color,border-color] duration-150",
                  i.severity === "error"
                    ? "border-danger/25 bg-danger-soft/40 hover:bg-danger-soft/70"
                    : "border-warning/30 bg-warning-soft/40 hover:bg-warning-soft/70",
                )}
              >
                {i.severity === "error" ? (
                  <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger-text" aria-label="Error" />
                ) : (
                  <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-text" aria-label="Warning" />
                )}
                <button type="button" onClick={() => onPick(i)} className={cn("min-w-0 flex-1 cursor-pointer text-left", focusRing)}>
                  <span className="block truncate text-[12px] font-medium text-fg-2">{labelOf(i)}</span>
                  <span className="block text-[12.5px] leading-relaxed text-fg">{i.message}</span>
                </button>
                {i.code === "E_DANGLING_EDGE" && i.edge_id && (
                  <Button size="sm" variant="ghost" icon={<Trash2 aria-hidden />} onClick={() => onRemoveEdge(i.edge_id!)}>
                    Remove
                  </Button>
                )}
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </div>
  );
}
