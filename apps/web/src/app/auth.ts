/** Sign-in state for components, plus the sign-in and sign-out transitions (T039, T040). */
import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { RegisteredSession, Session } from "../api/types";
import { authChannel } from "./authChannel";
import { queryClient } from "./queryClient";
import { session } from "./session";

/** Re-renders when the session changes in this tab or another (storage event). */
export function useSignedIn(): boolean {
  return useSyncExternalStore(
    (l) => session.subscribe(l),
    () => session.isSignedIn(),
    () => false,
  );
}

/** Accepts only same-origin app paths for `?next=` so sign-in cannot redirect off-site. */
export function safeNext(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (/^\/(login|register|verify-email|forgot-password|reset-password)\b/.test(next)) return fallback;
  return next;
}

export function loginPathFor(location: { pathname: string; search: string; hash?: string }): string {
  const next = `${location.pathname}${location.search}${location.hash ?? ""}`;
  return next === "/" || next === "" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
}

/** Registration answered with session tokens (a demo API with AUTH_AUTO_VERIFY_EMAIL). */
export function isRegisteredSession(result: unknown): result is RegisteredSession {
  if (typeof result !== "object" || result === null) return false;
  const r = result as Partial<RegisteredSession>;
  return r.status === "signed_in" && typeof r.access_token === "string" && typeof r.refresh_token === "string";
}

export function startSession(s: Session) {
  queryClient.clear();
  session.set(s);
  authChannel.post({ type: "signed_in" });
}

/**
 * Global sign-out (US1.3): revoke on the server, drop tokens and cached data, and tell every
 * other tab. The local part runs even when the network call fails.
 */
export async function signOut() {
  try {
    await api.POST("/auth/sign-out");
  } catch {
    /* offline: still sign out locally */
  }
  session.clear();
  queryClient.clear();
  authChannel.post({ type: "signed_out" });
}

let wired = false;
/** Other tabs signing out clear this tab's cache; the guard then redirects via useSignedIn. */
export function wireCrossTabAuth() {
  if (wired) return;
  wired = true;
  authChannel.listen((e) => {
    if (e.type === "signed_out") {
      queryClient.clear();
      session.clear();
    }
  });
}
