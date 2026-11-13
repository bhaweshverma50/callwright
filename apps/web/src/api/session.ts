/**
 * The signed-in session (T039, T040). Tokens live in localStorage so every tab shares one session;
 * sign-out in any tab is broadcast through authChannel so the others drop their cache at once (R8).
 * Every storage access is wrapped: private windows and blocked storage fall back to memory.
 */
import { useSyncExternalStore } from "react";
import { authChannel } from "./authChannel";
import type { QueryClient } from "@tanstack/react-query";
import type { Session } from "./types";

type StoredSession = Pick<Session, "access_token" | "refresh_token">;

const KEY = "cw.session";
let memory: StoredSession | null = null;
const listeners = new Set<() => void>();

function read(): StoredSession | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return memory;
  }
}

function write(s: StoredSession | null) {
  memory = s;
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: memory copy is used */
  }
  listeners.forEach((l) => l());
}

export const session = {
  isSignedIn: () => read() !== null,
  accessToken: () => read()?.access_token ?? null,
  refreshToken: () => read()?.refresh_token ?? null,
  set(s: Session) {
    write({ access_token: s.access_token, refresh_token: s.refresh_token });
  },
  clear() {
    write(null);
  },
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

// Another tab changed the stored session (sign-in or sign-out there).
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) listeners.forEach((l) => l());
  });
}

/** Re-renders when the session changes in this tab or another (storage event). */
export function useSignedIn(): boolean {
  return useSyncExternalStore(
    (l) => session.subscribe(l),
    () => session.isSignedIn(),
    () => false,
  );
}

/** The query cache the session clears when it starts or ends; App binds the one it provides. */
let cache: QueryClient | null = null;

export function bindSessionCache(qc: QueryClient) {
  cache = qc;
  return () => {
    if (cache === qc) cache = null;
  };
}

/**
 * Idle sign-out: the last time a person used the app in any tab (input, not background polling).
 * Shared through localStorage, so a laptop left closed overnight is signed out when it reopens.
 */
const ACTIVE_KEY = "cw.lastActive";
export const IDLE_LIMIT_MS = 8 * 60 * 60 * 1000;
let lastWrite = 0;

export function touchActivity(force = false) {
  const now = Date.now();
  if (!force && now - lastWrite < 30_000) return; // ponytail: one write per 30 s is precise enough
  lastWrite = now;
  try {
    localStorage.setItem(ACTIVE_KEY, String(now));
  } catch {
    /* storage unavailable: idle sign-out is skipped, the server's session lifetime still applies */
  }
}

/** Milliseconds since the last activity, or 0 when none is recorded (a session from before this). */
export function idleFor(): number {
  try {
    const last = Number(localStorage.getItem(ACTIVE_KEY));
    return last > 0 ? Date.now() - last : 0;
  } catch {
    return 0;
  }
}

export function startSession(s: Session) {
  cache?.clear();
  touchActivity(true);
  session.set(s);
  authChannel.post({ type: "signed_in" });
}

function dropSession() {
  session.clear();
  cache?.clear();
}

/**
 * Every way a session ends (sign-out, a refresh the server refused, a session /me rejects): drop
 * tokens and cached data here and tell every other tab. The guard then redirects via useSignedIn.
 */
export function endSession() {
  dropSession();
  authChannel.post({ type: "signed_out" });
}

let wired = false;
/** Another tab signing out drops this tab's session and cache without echoing the event back. */
export function wireCrossTabAuth() {
  if (wired) return;
  wired = true;
  authChannel.listen((e) => {
    if (e.type === "signed_out") dropSession();
  });
}
