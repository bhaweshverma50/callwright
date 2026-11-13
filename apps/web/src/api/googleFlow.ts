/**
 * "Continue with Google" browser side: remembers the flow across the redirect to Google and posts
 * the returned code once.
 *
 * The state is kept in sessionStorage (this tab only) next to the page to return to. The callback
 * accepts a state only when it matches, so a link someone else started cannot sign this browser
 * into their account. Storage that cannot be read does not block sign-in.
 */
import { completeGoogleSignIn } from "./auth";
import type { Session } from "./types";

const KEY = "cw.google";

interface PendingFlow {
  state: string;
  next: string | null;
}

export function rememberGoogleFlow(authorizationUrl: string, next: string | null) {
  const state = new URL(authorizationUrl).searchParams.get("state");
  if (!state) return;
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ state, next } satisfies PendingFlow));
  } catch {
    /* storage unavailable: the state check is skipped on the way back */
  }
}

function read(): { readable: boolean; flow: PendingFlow | null } {
  try {
    const raw = sessionStorage.getItem(KEY);
    return { readable: true, flow: raw ? (JSON.parse(raw) as PendingFlow) : null };
  } catch {
    return { readable: false, flow: null };
  }
}

/** True when this tab started the flow with `state` (or storage cannot tell). */
export function isOurGoogleFlow(state: string): boolean {
  const { readable, flow } = read();
  return !readable || flow?.state === state;
}

/** Where to go after signing in, as saved when the flow started. */
export function googleFlowNext(): string | null {
  return read().flow?.next ?? null;
}

export function forgetGoogleFlow() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to forget */
  }
}

/** A code works once and React StrictMode runs effects twice in development, so one request is
 * shared per state. */
const inflight = new Map<string, Promise<Session>>();

export function completeGoogleOnce(code: string, state: string): Promise<Session> {
  let p = inflight.get(state);
  if (!p) {
    p = completeGoogleSignIn(code, state);
    inflight.set(state, p);
  }
  return p;
}
