/**
 * Token storage (T039). Tokens live in localStorage so every tab shares one session; sign-out in
 * any tab is broadcast through authChannel so the others drop their cache at once (R8).
 * Every storage access is wrapped: private windows and blocked storage fall back to memory.
 */
import type { Session } from "../api/types";

export interface StoredSession {
  access_token: string;
  refresh_token: string;
  /** Epoch milliseconds when the access token expires. */
  expires_at: number;
}

const KEY = "cw.session";
let memory: StoredSession | null = null;
const listeners = new Set<(s: StoredSession | null) => void>();

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
  listeners.forEach((l) => l(s));
}

export const session = {
  get: read,
  isSignedIn: () => read() !== null,
  accessToken: () => read()?.access_token ?? null,
  refreshToken: () => read()?.refresh_token ?? null,
  set(s: Session) {
    write({
      access_token: s.access_token,
      refresh_token: s.refresh_token,
      expires_at: Date.now() + s.expires_in * 1000,
    });
  },
  clear() {
    write(null);
  },
  subscribe(fn: (s: StoredSession | null) => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

// Another tab changed the stored session (sign-in or sign-out there).
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) listeners.forEach((l) => l(read()));
  });
}
