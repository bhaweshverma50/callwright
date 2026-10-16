/**
 * Typed API client (T025). Generated types come from the spec contracts via
 * scripts/gen-api.mjs; requests go through openapi-fetch.
 *
 * Auth: every request carries the bearer token. A 401 on a protected call triggers one silent
 * refresh (single-flight across concurrent requests) and a single retry. When refresh fails the
 * session is cleared, other tabs are told, and `onSessionExpired` sends the user to sign-in
 * with a return path (US1.3, edge case "session token expires mid-session").
 *
 * Lazy feature credentials (FR-020, T098): tokens for optional features (voice copilot STT key,
 * web test-call room token, analytics assistant session) are fetched by `useLazyToken(feature)`
 * hooks only when the user first opens that feature. Never request them from the shell, route
 * loaders or on page load; eslint.config.js blocks token queries in app/Shell.tsx.
 */
import createClient from "openapi-fetch";
import { env } from "../lib/env";
import { session } from "../app/session";
import { authChannel } from "../app/authChannel";
import { ApiError, networkError, toProblem } from "./errors";
import type { paths, Session } from "./types";

type Expired = () => void;
let onSessionExpired: Expired = () => {};
export function setSessionExpiredHandler(fn: Expired) {
  onSessionExpired = fn;
}

let refreshing: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  const refresh_token = session.refreshToken();
  if (!refresh_token) return false;
  refreshing ??= (async () => {
    try {
      const res = await globalThis.fetch(`${env.apiBaseUrl}/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) return false;
      session.set((await res.json()) as Session);
      return true;
    } catch {
      return false;
    } finally {
      queueMicrotask(() => {
        refreshing = null;
      });
    }
  })();
  return refreshing;
}

function withToken(req: Request): Request {
  const token = session.accessToken();
  if (!token) return req;
  const headers = new Headers(req.headers);
  headers.set("authorization", `Bearer ${token}`);
  return new Request(req, { headers });
}

const isAuthPath = (url: string) => /\/auth\/(sign-in|register|refresh|verify-email|password-reset)/.test(url);

async function authFetch(input: Request): Promise<Response> {
  const retryCopy = input.clone();
  let res: Response;
  try {
    res = await globalThis.fetch(withToken(input));
  } catch {
    throw networkError();
  }
  if (res.status !== 401 || isAuthPath(input.url) || !session.isSignedIn()) return res;

  if (await refreshOnce()) {
    try {
      return await globalThis.fetch(withToken(retryCopy));
    } catch {
      throw networkError();
    }
  }
  session.clear();
  authChannel.post({ type: "signed_out" });
  onSessionExpired();
  return res;
}

export const api = createClient<paths>({ baseUrl: env.apiBaseUrl, fetch: authFetch });

/**
 * Unwraps an openapi-fetch result: returns data or throws ApiError with the problem body.
 * Use inside TanStack Query functions so errors reach error states and boundaries.
 */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  throw new ApiError(response.status, toProblem(response.status, error));
}
