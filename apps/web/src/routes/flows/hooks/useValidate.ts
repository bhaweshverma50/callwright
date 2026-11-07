import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import { flowKeys, validateFlow, type FlowGraph, type FlowValidationResult } from "../../../api/flows";
import { useDebounced } from "../../../lib/useDebounced";
import { stable } from "../../../lib/stable";

export const VALIDATE_DEBOUNCE_MS = 600;

/**
 * Server-side validation of the unsaved graph, 600 ms after the last edit (research R5), cached
 * per graph like the single-prompt editor's validation. The last result stays on screen while the
 * next one is computed. Only the steps and connections matter: a pan or zoom changes the graph's
 * viewport and never asks the server again.
 */
export function useValidate(flowId: string | null, graph: FlowGraph, initial: FlowValidationResult | null) {
  const qc = useQueryClient();
  const { nodes, edges } = graph;
  const shape = useMemo(() => ({ nodes, edges }), [nodes, edges]);
  const shapeKey = useMemo(() => stable(shape), [shape]);
  const debounced = useDebounced(shape, VALIDATE_DEBOUNCE_MS);
  const debouncedKey = useMemo(() => stable(debounced), [debounced]);
  const initialKey = useRef(shapeKey);
  const viewport = useRef(graph.viewport);
  viewport.current = graph.viewport;

  const query = useQuery({
    queryKey: [...flowKeys.validate(flowId ?? ""), debouncedKey],
    queryFn: ({ signal }) => validateFlow(flowId!, { ...debounced, viewport: viewport.current }, signal),
    initialData: debouncedKey === initialKey.current && initial ? initial : undefined,
    enabled: Boolean(flowId),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });

  /** A result the server returned another way (save, publish) for the graph as it is now. */
  const setResult = useCallback(
    (r: FlowValidationResult) => qc.setQueryData([...flowKeys.validate(flowId ?? ""), shapeKey], r),
    [qc, flowId, shapeKey],
  );

  return { result: query.data ?? null, checking: query.isFetching || debouncedKey !== shapeKey, setResult };
}
