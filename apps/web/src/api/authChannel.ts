/**
 * Cross-tab auth events (T039, US1.3). Sign-out in one tab makes every other tab drop its query
 * cache and return to /login?next=<its current path> immediately.
 */
export type AuthEvent = { type: "signed_out" } | { type: "signed_in" };

const NAME = "callwright-auth";
let channel: BroadcastChannel | null = null;

function getChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  channel ??= new BroadcastChannel(NAME);
  return channel;
}

export const authChannel = {
  post(event: AuthEvent) {
    try {
      getChannel()?.postMessage(event);
    } catch {
      /* closed channel: the storage event (session.ts) still reaches other tabs */
    }
  },
  listen(fn: (event: AuthEvent) => void) {
    const ch = getChannel();
    if (!ch) return () => {};
    const handler = (e: MessageEvent<AuthEvent>) => fn(e.data);
    ch.addEventListener("message", handler);
    return () => ch.removeEventListener("message", handler);
  },
};
