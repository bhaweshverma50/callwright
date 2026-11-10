import { useCallback, useEffect, useState } from "react";
import { onRoomData } from "../../../webCall/roomData";

/**
 * Live node highlight during a builder test call (FR-033, T069): the worker announces every node
 * entry on the room's data channel ("flow") as `{type: "node_entered", node_id}`.
 */
export function useFlowEvents() {
  const [active, setActive] = useState<string | null>(null);
  const [visited, setVisited] = useState<Set<string>>(() => new Set());

  useEffect(
    () =>
      onRoomData("flow", ({ node_id }) => {
        setActive(node_id);
        setVisited((v) => new Set(v).add(node_id));
      }),
    [],
  );

  const reset = useCallback(() => {
    setActive(null);
    setVisited(new Set());
  }, []);

  return { active, visited, reset };
}
