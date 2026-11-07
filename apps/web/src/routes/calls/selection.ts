/**
 * Cross-page call selection for "Run simulation" (FR-006): kept while paging, from a single agent,
 * and no more calls than one batch takes. The selection opens the 008 start dialog in place (one
 * call starts an individual run, more start a batch).
 */
import { useCallback, useState } from "react";
import { bodyLimits } from "../../lib/contract.gen";

export const MAX_SELECTION = bodyLimits["POST /experiments"].base_call_ids.maxItems;

export type Selection = ReadonlyMap<string, string>; // call id -> agent id

export type SimulationCheck = { ok: true; agentId: string } | { ok: false; reason: string };

export function checkSimulation(selection: Selection): SimulationCheck {
  if (selection.size === 0) return { ok: false, reason: "Select calls to run a simulation." };
  if (selection.size > MAX_SELECTION) return { ok: false, reason: `Select at most ${MAX_SELECTION} calls to run a simulation.` };
  const agents = new Set(selection.values());
  if (agents.size > 1) return { ok: false, reason: "Select calls from a single agent to run a simulation" };
  return { ok: true, agentId: [...agents][0]! };
}

export function useCallSelection() {
  const [selection, setSelection] = useState<Map<string, string>>(() => new Map());
  const [limitHit, setLimitHit] = useState(false);

  const toggle = useCallback((id: string, agentId: string) => {
    setSelection((prev) => {
      const next = new Map(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size >= MAX_SELECTION) {
        setLimitHit(true);
        return prev;
      } else next.set(id, agentId);
      return next;
    });
  }, []);

  /** Ticks (or clears, when every row is ticked) the rows of the current page. */
  const togglePage = useCallback((rows: { id: string; agentId: string }[]) => {
    setSelection((prev) => {
      const next = new Map(prev);
      const allOn = rows.length > 0 && rows.every((r) => next.has(r.id));
      for (const r of rows) {
        if (allOn) next.delete(r.id);
        else if (!next.has(r.id)) {
          if (next.size >= MAX_SELECTION) {
            setLimitHit(true);
            break;
          }
          next.set(r.id, r.agentId);
        }
      }
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setSelection(new Map());
    setLimitHit(false);
  }, []);

  return { selection, toggle, togglePage, clear, limitHit };
}
