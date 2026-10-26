import { useCallback, useEffect, useState } from "react";
import { ROOM_DATA_EVENT } from "../../../components/webCallLive";

export const FLOW_TOPIC = "callwright.flow";

/**
 * Live node highlight during a builder test call (FR-033, T069): the worker announces every node
 * entry on the room's data channel, topic `callwright.flow`, as `{type: "node_entered", node_id}`.
 */
export function useFlowEvents() {
  const [active, setActive] = useState<string | null>(null);
  const [visited, setVisited] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const onData = (e: Event) => {
      const { topic, payload } = (e as CustomEvent<{ topic?: string; payload: Uint8Array }>).detail;
      if (topic !== FLOW_TOPIC) return;
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload)) as { type?: string; node_id?: string };
        if (msg.type !== "node_entered" || !msg.node_id) return;
        setActive(msg.node_id);
        setVisited((v) => new Set(v).add(msg.node_id!));
      } catch {
        /* not a flow message */
      }
    };
    window.addEventListener(ROOM_DATA_EVENT, onData);
    return () => window.removeEventListener(ROOM_DATA_EVENT, onData);
  }, []);

  const reset = useCallback(() => {
    setActive(null);
    setVisited(new Set());
  }, []);

  return { active, visited, reset };
}
