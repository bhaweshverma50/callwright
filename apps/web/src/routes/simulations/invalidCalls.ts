import type { AddItemsResult, InvalidReason } from "../../api/datasets";

/** Why a call cannot be replayed or added to a dataset, in the operator's words. */
export const INVALID_REASONS: Record<InvalidReason, string> = {
  not_found: "Call not found",
  wrong_agent: "Belongs to another agent",
  simulated_call: "Simulated calls cannot be added",
  not_completed: "The call did not complete",
  unavailable: "Transcript removed by retention",
};

/** "3 added, 1 already in the dataset, 1 skipped: Belongs to another agent". */
export function describeAddResult(r: AddItemsResult): string {
  const parts = [`${r.added} added`];
  if (r.skipped_duplicates) parts.push(`${r.skipped_duplicates} already in the dataset`);
  if (r.skipped_invalid) {
    const reasons = [...new Set(r.invalid.map((i) => INVALID_REASONS[i.reason]))];
    parts.push(`${r.skipped_invalid} skipped: ${reasons.join("; ").toLowerCase()}`);
  }
  return parts.join(", ");
}
