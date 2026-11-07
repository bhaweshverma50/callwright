/**
 * Messages the voice worker publishes on the call room's data channel, and the one way for the
 * web app to listen to them. The topic strings are the worker's (worker/metrics.py LATENCY_TOPIC,
 * worker/flow/events.py TOPIC); this is their only home on the web side.
 */

/** Data channel topics the worker publishes on. */
export const ROOM_TOPICS = {
  /** Per-turn latency split: JSON `{turn_index, stt_ms, llm_ms, tts_ms, e2e_ms?}`. */
  latency: "cw.turn_latency",
  /** Flow node announcements during a builder test call: JSON `{type: "node_entered", node_id}`. */
  flow: "callwright.flow",
} as const;

export type RoomTopic = (typeof ROOM_TOPICS)[keyof typeof ROOM_TOPICS];

type Listener = (payload: Uint8Array) => void;
const listeners = new Map<string, Set<Listener>>();

/** Calls `cb` with every payload the live call receives on `topic`; returns the unsubscribe. */
export function onRoomData(topic: RoomTopic, cb: Listener): () => void {
  let set = listeners.get(topic);
  if (!set) listeners.set(topic, (set = new Set()));
  set.add(cb);
  return () => void set.delete(cb);
}

/** Hands one received message to the listeners of its topic (the live driver calls this). */
export function publishRoomData(topic: string | undefined, payload: Uint8Array) {
  if (!topic) return;
  for (const cb of listeners.get(topic) ?? []) cb(payload);
}
