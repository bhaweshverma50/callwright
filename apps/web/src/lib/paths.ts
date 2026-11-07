/**
 * Every in-app address built outside the router, so a page moving changes one place. The router
 * (src/router.tsx) mounts its routes on the same values.
 */

export const DASHBOARD_PATH = "/dashboard";
export const BILLING_PATH = "/billing";
export const SETTINGS_PATH = "/settings";
export const AGENTS_PATH = "/agents";
export const CALLS_PATH = "/calls";

/** Public sign-in pages; `?next=` never points back at one of them. */
export const AUTH_PAGES = {
  login: "/login",
  register: "/register",
  verifyEmail: "/verify-email",
  forgotPassword: "/forgot-password",
  resetPassword: "/reset-password",
} as const;

const AUTH_PAGE_SET = new Set<string>(Object.values(AUTH_PAGES));

/** Agent ids are `agt_` and a Crockford ULID. */
const AGENT_ID = /^agt_[0-9A-HJKMNP-TV-Z]{26}$/;
export const isAgentId = (id: string) => AGENT_ID.test(id);

type AgentRef = { id: string; type?: "single_prompt" | "flow" | null };

/** The agent's builder: the flow canvas for flow agents, the editor otherwise. Without a type,
 * `/agents/:id` opens the right one after loading the agent. */
export function agentPath(a: AgentRef): string {
  if (!a.type) return `${AGENTS_PATH}/${a.id}`;
  return a.type === "flow" ? `${AGENTS_PATH}/${a.id}/flow` : `${AGENTS_PATH}/${a.id}/edit`;
}

type CallsQuery = Record<string, string | readonly string[] | null | undefined>;

/** Call History's address state: list values join with commas, empty values are left out. */
export function callsSearch(query: CallsQuery): URLSearchParams {
  const out = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    const v = typeof value === "string" ? value : value?.join(",");
    if (v) out.set(key, v);
  }
  return out;
}

/** Call History filtered by `query`; no filters is plain `/calls`. */
export function callsPath(query: CallsQuery = {}): string {
  const s = callsSearch(query).toString();
  return s ? `${CALLS_PATH}?${s}` : CALLS_PATH;
}

export const agentEditPath = (id: string) => `${AGENTS_PATH}/${id}/edit`;
export const agentFlowPath = (id: string) => `${AGENTS_PATH}/${id}/flow`;
export const agentTestingPath = (id: string) => `${AGENTS_PATH}/${id}/testing`;

/** Accepts only same-origin app paths for `?next=` so sign-in cannot redirect off-site. */
export function safeNext(next: string | null | undefined, fallback = DASHBOARD_PATH): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  const page = /^\/[^/?#]*/.exec(next)?.[0] ?? "";
  if (AUTH_PAGE_SET.has(page)) return fallback;
  return next;
}

export function loginPathFor(location: { pathname: string; search: string; hash?: string }): string {
  const next = `${location.pathname}${location.search}${location.hash ?? ""}`;
  return next === "/" || next === "" ? AUTH_PAGES.login : `${AUTH_PAGES.login}?next=${encodeURIComponent(next)}`;
}
