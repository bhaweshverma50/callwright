/**
 * The signed-in session (T039, T040). Tokens live in localStorage so every tab shares one session;
 * sign-out in any tab is broadcast through authChannel so the others drop their cache at once (R8).
 * Every storage access is wrapped: private windows and blocked storage fall back to memory.
 */
import { useSyncExternalStore } from "react";
import { authChannel } from "./authChannel";
import { queryClient } from "./queryClient";
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

export function startSession(s: Session) {
  queryClient.clear();
  session.set(s);
  authChannel.post({ type: "signed_in" });
}

function dropSession() {
  session.clear();
  queryClient.clear();
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
