import { useEffect, useRef, useState } from "react";
import { validateFlow, type FlowGraph, type FlowValidationResult } from "../../../api/flows";

export const VALIDATE_DEBOUNCE_MS = 600;

/**
 * Server-side validation of the unsaved graph, 600 ms after the last edit (research R5). The
 * last result stays on screen while the next one is computed; requests that a newer edit made
 * stale are aborted.
 */
export function useValidate(flowId: string | null, graph: FlowGraph, initial: FlowValidationResult | null) {
  const [result, setResult] = useState<FlowValidationResult | null>(initial);
  const [checking, setChecking] = useState(false);
  const first = useRef(true);

  useEffect(() => {
    if (!flowId) return;
    if (first.current) {
      first.current = false;
      if (initial) return;
    }
    const ctrl = new AbortController();
    setChecking(true);
    const timer = window.setTimeout(() => {
      validateFlow(flowId, graph, ctrl.signal)
        .then((r) => {
          if (!ctrl.signal.aborted) setResult(r);
        })
        .catch(() => {})
        .finally(() => {
          if (!ctrl.signal.aborted) setChecking(false);
        });
    }, VALIDATE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [flowId, graph, initial]);

  return { result, checking, setResult };
}
