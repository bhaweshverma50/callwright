/**
 * Typed API client (T025). Generated types come from the spec contracts via
 * scripts/gen-api.mjs; requests go through openapi-fetch.
 *
 * Auth: every request carries the bearer token. A 401 on a protected call triggers one silent
 * refresh (single-flight across concurrent requests) and a single retry. When refresh fails the
 * session ends (session.ts) and the auth guard sends the user to sign-in with a return path
 * (US1.3, edge case "session token expires mid-session").
 *
 * Hosted demo: a 503 `waking_up` (the call servers are starting) is held at the wake gate and the
 * request retried; see wakeGate.ts and WakeOverlay.
 *
 * Lazy feature credentials (FR-020, T098): tokens for optional features (voice copilot STT key,
 * web test-call room token, analytics assistant session) are fetched only when the user first
 * opens that feature. Never request them from the shell, route loaders or on page load;
 * eslint.config.js blocks token queries in app/Shell.tsx.
 */
import createClient, { type ClientPathsWithMethod, type MethodResponse } from "openapi-fetch";
import { env } from "../lib/env";
import { ApiError, networkError, toProblem } from "./errors";
import { endSession, session } from "./session";
import type { paths } from "./types";
import { wakeAwareFetch } from "./wakeGate";

const REFRESH: keyof paths = "/auth/refresh";
/** Endpoints that answer 401 for a wrong password or token, not for an expired session. */
const PUBLIC_AUTH_ENDPOINTS: (keyof paths)[] = ["/auth/sign-in", "/auth/register", REFRESH, "/auth/verify-email", "/auth/password-reset"];
const isPublicAuthCall = (url: string) => PUBLIC_AUTH_ENDPOINTS.some((p) => url.includes(p));

async function isWrongPassword(res: Response): Promise<boolean> {
  const body: unknown = await res
    .clone()
    .json()
    .catch(() => null);
  return typeof body === "object" && body !== null && (body as { code?: unknown }).code === "invalid_credentials";
}

let refreshing: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  const refresh_token = session.refreshToken();
  if (!refresh_token) return false;
  refreshing ??= (async () => {
    try {
      // Through the wake gate: a refresh while the call servers start must wait, not sign out.
      const res = await wakeAwareFetch(() =>
        globalThis.fetch(`${env.apiBaseUrl}${REFRESH}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ refresh_token }),
        }),
      );
      if (!res.ok) return false;
      session.set(await res.json());
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

/**
 * Sends one request with the current token through the wake gate. On a 401 it refreshes once and
 * sends again; when the refresh fails the session ends. `send` builds a fresh request per attempt,
 * so any transport can use it (the knowledge upload uses XHR for progress).
 */
export async function sendAuthorized(send: (token: string | null) => Promise<Response>, url = ""): Promise<Response> {
  const attempt = async () => {
    try {
      return await wakeAwareFetch(() => send(session.accessToken()));
    } catch {
      throw networkError();
    }
  };
  const res = await attempt();
  if (res.status !== 401 || isPublicAuthCall(url) || !session.isSignedIn()) return res;
  // A wrong password on a signed-in action (change password, delete account) is not an expired
  // session: refreshing and sending it again would count a second failed attempt.
  if (await isWrongPassword(res)) return res;
  if (await refreshOnce()) return attempt();
  endSession();
  return res;
}

function authFetch(input: Request): Promise<Response> {
  const template = input.clone();
  return sendAuthorized((token) => {
    const req = template.clone();
    if (!token) return globalThis.fetch(req);
    const headers = new Headers(req.headers);
    headers.set("authorization", `Bearer ${token}`);
    return globalThis.fetch(new Request(req, { headers }));
  }, input.url);
}

export const api = createClient<paths>({ baseUrl: env.apiBaseUrl, fetch: authFetch });

/**
 * Unwraps an openapi-fetch result: returns data or throws ApiError with the problem body.
 * Use inside TanStack Query functions so errors reach error states and boundaries.
 */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  throw new ApiError(response.status, toProblem(response.status, error));
}

type FormPath = ClientPathsWithMethod<typeof api, "post">;

/** Fills `{name}` segments of a contract path. */
export function apiUrl(path: string, params: Record<string, string> = {}): string {
  return `${env.apiBaseUrl}${path.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(params[k] ?? ""))}`;
}

/** Reads a JSON body from a response sent outside openapi-fetch, throwing ApiError when it failed. */
export async function readJson<T>(res: Response): Promise<T> {
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, toProblem(res.status, body));
  return body as T;
}

/**
 * Multipart upload (openapi-fetch has no file body helper) with the same auth, refresh and wake
 * handling as every other call. The response is typed from the contract.
 */
export async function postForm<P extends FormPath>(
  path: P,
  form: FormData,
  params?: Record<string, string>,
): Promise<MethodResponse<typeof api, "post", P>> {
  const url = apiUrl(path, params);
  const res = await sendAuthorized(
    (token) => globalThis.fetch(url, { method: "POST", body: form, headers: token ? { authorization: `Bearer ${token}` } : {} }),
    url,
  );
  return readJson(res);
}

/** Rows per page when a loader reads a whole collection: the largest page the contract allows. */
const ALL_PAGE_SIZE = 100;
/** Page cap for whole-collection loaders (5,000 rows): past this a picker or menu is unusable anyway. */
const MAX_PAGES = 50;

/**
 * Reads every page of a paged list, for pickers, menus and lists that need the whole collection.
 * The one rule for "all": 100-row pages, stopping at the last page or after 50 pages.
 */
export async function fetchAll<T>(load: (page: { page: number; page_size: number }) => Promise<{ items: T[]; total_pages: number }>): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const res = await load({ page, page_size: ALL_PAGE_SIZE });
    out.push(...res.items);
    if (page >= res.total_pages) break;
  }
  return out;
}
