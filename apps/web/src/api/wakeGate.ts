/**
 * Wake gate for the hosted demo. The call servers (Redis, LiveKit, workers) run on a VM that powers
 * off when idle; while it starts, the API answers 503 problem+json `code: waking_up`. The first
 * such response opens the gate: that request is retried with backoff until the API answers
 * something else (about a minute), and every other request waits behind the gate instead of
 * failing on its own. Once the servers answer, waiting requests are sent again. After
 * WAKE_TIMEOUT_MS the gate fails: callers get their 503 and the overlay (WakeOverlay) offers a
 * retry. The overlay reads the state through `useWakeState`.
 */
import { useSyncExternalStore } from "react";

export type WakeState =
  { status: "idle" } | { status: "waking"; startedAt: number; attempts: number } | { status: "failed"; startedAt: number; attempts: number };

export const WAKE_TIMEOUT_MS = 180_000;
/** Typical start time, used for the progress bar. */
export const WAKE_EXPECTED_MS = 75_000;

type Send = () => Promise<Response>;
type Outcome = { ok: true; response: Response } | { ok: false };

const defaults = {
  backoffMs: [2_000, 3_000, 5_000, 8_000, 10_000, 15_000],
  timeoutMs: WAKE_TIMEOUT_MS,
  now: () => Date.now(),
  sleep: (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)),
};
let config = { ...defaults };

let state: WakeState = { status: "idle" };
let gate: Promise<Outcome> | null = null;
const listeners = new Set<() => void>();

function setState(next: WakeState) {
  state = next;
  listeners.forEach((l) => l());
}

export const wakeStore = {
  get: () => state,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
};

export function useWakeState(): WakeState {
  return useSyncExternalStore(wakeStore.subscribe, wakeStore.get, wakeStore.get);
}

/** True for the API's 503 `waking_up` problem. Reads a clone, so the response stays unread. */
export async function isWakingUp(res: Response): Promise<boolean> {
  if (res.status !== 503) return false;
  try {
    const body = (await res.clone().json()) as { code?: unknown } | null;
    return body?.code === "waking_up";
  } catch {
    return false;
  }
}

function openGate(send: Send): Promise<Outcome> {
  const startedAt = config.now();
  setState({ status: "waking", startedAt, attempts: 0 });
  const run = async (): Promise<Outcome> => {
    for (let attempt = 0; ; attempt++) {
      const wait = config.backoffMs[Math.min(attempt, config.backoffMs.length - 1)] ?? 15_000;
      if (config.now() + wait - startedAt > config.timeoutMs) {
        setState({ status: "failed", startedAt, attempts: attempt });
        return { ok: false };
      }
      await config.sleep(wait);
      setState({ status: "waking", startedAt, attempts: attempt + 1 });
      try {
        const response = await send();
        if (!(await isWakingUp(response))) {
          setState({ status: "idle" });
          return { ok: true, response };
        }
      } catch {
        /* network blip while the servers start: keep trying */
      }
    }
  };
  gate = run().finally(() => {
    gate = null;
  });
  return gate;
}

/**
 * Sends a request through the gate. `send` must build a fresh request on every call (it may run
 * several times). Requests issued while the gate is open wait for it before going out.
 */
export async function wakeAwareFetch(send: Send): Promise<Response> {
  if (gate) await gate;
  let response = await send();
  while (await isWakingUp(response)) {
    if (state.status === "failed") return response;
    if (gate) {
      // Another request is already waiting for the servers: queue behind it, then go again.
      const outcome = await gate;
      if (!outcome.ok) return response;
      response = await send();
      continue;
    }
    // This request leads: it is retried until the servers answer, and its answer is used.
    const outcome = await openGate(send);
    return outcome.ok ? outcome.response : response;
  }
  return response;
}

/** After a failed wake: back to normal so the next requests try again (the overlay's Retry). */
export function resetWake() {
  if (state.status === "failed") setState({ status: "idle" });
}

/** Test hooks: shorter backoff, fake clock, and a clean slate between tests. */
export function configureWake(overrides: Partial<typeof defaults>) {
  config = { ...config, ...overrides };
}

export function resetWakeForTests() {
  config = { ...defaults };
  gate = null;
  setState({ status: "idle" });
}
