import { Check, CircleAlert, PenLine, X } from "lucide-react";
import { motion } from "motion/react";
import type { FlowGraph, ValidationIssue } from "../../../api/flows";
import { Button } from "../../../components";
import type { GraphDiff } from "../canvas/diffOverlay";

export interface Proposal {
  message: string;
  graph: FlowGraph;
  name: string | null;
  issues: ValidationIssue[];
  baseRevision: number;
}

/** What approving a proposal does to the draft: the whole proposal is one undo step (FR-037). */
export function approveProposal(proposal: Proposal, setGraph: (g: FlowGraph, record?: boolean) => void, setName: (n: string) => void) {
  setGraph(proposal.graph, true);
  if (proposal.name) setName(proposal.name);
}

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * Pending changes from the assistant (T092): what they add, change and remove, the problems the
 * result would have, and Approve or Decline. Nothing changes until Approve; Decline leaves the
 * canvas exactly as it was.
 */
export function ProposalBar({
  proposal,
  diff,
  onApprove,
  onDecline,
}: {
  proposal: Proposal;
  diff: GraphDiff;
  onApprove: () => void;
  onDecline: () => void;
}) {
  const c = diff.counts;
  const parts = [
    c.addedNodes && `+${plural(c.addedNodes, "step")}`,
    c.updatedNodes && `${plural(c.updatedNodes, "step")} changed`,
    c.removedNodes && `-${plural(c.removedNodes, "step")}`,
    c.addedEdges && `+${plural(c.addedEdges, "connection")}`,
    c.removedEdges && `-${plural(c.removedEdges, "connection")}`,
    c.updatedEdges && `${plural(c.updatedEdges, "connection")} changed`,
    proposal.name && `renamed to ${proposal.name}`,
  ].filter(Boolean);
  const errors = proposal.issues.filter((i) => i.severity === "error");
  return (
    <motion.div
      role="region"
      aria-label="Pending changes"
      initial={{ opacity: 0, y: -10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
      className="pointer-events-auto flex w-[min(460px,calc(100%-24px))] flex-col gap-2.5 rounded-panel border border-line bg-surface/95 p-3 shadow-pop backdrop-blur-md"
    >
      <div className="flex items-center gap-3">
        <span className="bg-accent grid size-8 shrink-0 place-items-center rounded-control text-white" aria-hidden>
          <PenLine className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-fg">Pending changes</p>
          <p className="mt-0.5 text-[13px] text-fg-2">{parts.length ? parts.join(", ") : "No changes to the graph"}</p>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <Button size="sm" variant="ghost" icon={<X aria-hidden />} onClick={onDecline}>
            Decline
          </Button>
          <Button size="sm" variant="primary" icon={<Check aria-hidden />} onClick={onApprove}>
            Approve
          </Button>
        </div>
      </div>
      {errors.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-control bg-danger-soft/50 px-3 py-2">
          {errors.slice(0, 3).map((i, k) => (
            <li key={k} className="flex items-start gap-1.5 text-[12px] text-danger-text">
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {i.message}
            </li>
          ))}
          {errors.length > 3 && <li className="text-[12px] text-danger-text">and {errors.length - 3} more</li>}
        </ul>
      )}
    </motion.div>
  );
}
