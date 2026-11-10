/**
 * Messages the voice worker publishes on the call room's data channel, and the one way for the
 * web app to listen to them. Topics and message shapes come from the contract
 * (specs/003-voice-runtime/contracts/data_channel.yaml); this is the only place that reads the
 * bytes.
 */
import type { components } from "../api/schema";
import { dataChannelTopics } from "../lib/contract.gen";

/** Data channel topic of each message kind. */
export const ROOM_TOPICS = {
  latency: dataChannelTopics.TurnLatencyMessage,
  flow: dataChannelTopics.FlowNodeEnteredMessage,
} as const;

/** The message each kind carries. */
export interface RoomMessages {
  latency: components["schemas"]["TurnLatencyMessage"];
  flow: components["schemas"]["FlowNodeEnteredMessage"];
}

type Kind = keyof RoomMessages;
type Listener = (message: never) => void;
const listeners = new Map<Kind, Set<Listener>>();

/** Calls `cb` with every message of `kind` the live call receives; returns the unsubscribe. */
export function onRoomData<K extends Kind>(kind: K, cb: (message: RoomMessages[K]) => void): () => void {
  let set = listeners.get(kind);
  if (!set) listeners.set(kind, (set = new Set()));
  set.add(cb as Listener);
  return () => void set.delete(cb as Listener);
}

/** Hands one received message to the listeners of its topic (the live driver calls this). */
export function publishRoomData(topic: string | undefined, payload: Uint8Array) {
  const kind = (Object.keys(ROOM_TOPICS) as Kind[]).find((k) => ROOM_TOPICS[k] === topic);
  if (!kind) return;
  let message: unknown;
  try {
    message = JSON.parse(new TextDecoder().decode(payload));
  } catch (e) {
    console.warn(`Ignored a ${topic} message that is not JSON.`, e);
    return;
  }
  for (const cb of listeners.get(kind) ?? []) (cb as (m: unknown) => void)(message);
}
