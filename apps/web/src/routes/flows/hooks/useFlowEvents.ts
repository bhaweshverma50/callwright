import { useCallback, useEffect, useState } from "react";
import { onRoomData, ROOM_TOPICS } from "../../../webCall/roomData";

/**
 * Live node highlight during a builder test call (FR-033, T069): the worker announces every node
 * entry on the room's data channel (ROOM_TOPICS.flow) as `{type: "node_entered", node_id}`.
 */
export function useFlowEvents() {
  const [active, setActive] = useState<string | null>(null);
  const [visited, setVisited] = useState<Set<string>>(() => new Set());

  useEffect(
    () =>
      onRoomData(ROOM_TOPICS.flow, (payload) => {
        let msg: { type?: string; node_id?: string };
        try {
          msg = JSON.parse(new TextDecoder().decode(payload)) as typeof msg;
        } catch (e) {
          console.warn("Ignored a flow message that is not JSON.", e);
          return;
        }
        if (msg.type !== "node_entered" || !msg.node_id) return;
        const nodeId = msg.node_id;
        setActive(nodeId);
        setVisited((v) => new Set(v).add(nodeId));
      }),
    [],
  );

  const reset = useCallback(() => {
    setActive(null);
    setVisited(new Set());
  }, []);

  return { active, visited, reset };
}
