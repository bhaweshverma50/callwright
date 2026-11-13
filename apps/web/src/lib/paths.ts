import { scalarLimits } from "./contract.gen";
/**
 * The app's addresses. The router (src/router.tsx) mounts every page on these values and the rest
 * of the app links with them, so a page moving changes one place.
 */

export const DASHBOARD_PATH = "/dashboard";
export const BILLING_PATH = "/billing";
export const SETTINGS_PATH = "/settings";
export const AGENTS_PATH = "/agents";
export const CALLS_PATH = "/calls";
export const CALLBACKS_PATH = `${CALLS_PATH}/callbacks`;
export const KNOWLEDGE_PATH = "/knowledge-base";
export const PHONE_NUMBERS_PATH = "/phone-numbers";
export const REVIEW_PATH = "/review";
export const CALIBRATION_PATH = "/calibration";
export const SIMULATIONS_PATH = "/simulations";
export const DATASETS_PATH = "/datasets";
export const ISSUES_PATH = "/issues";

export const NEW_AGENT_PATH = `${AGENTS_PATH}/new`;
export const NEW_SINGLE_AGENT_PATH = `${NEW_AGENT_PATH}/single`;
export const NEW_FLOW_AGENT_PATH = `${NEW_AGENT_PATH}/flow`;
export const TEMPLATES_PATH = `${AGENTS_PATH}/templates`;
/** The gallery filtered to one agent type (the Agent type chooser and the new flow page link here). */
export const templatesPath = (type: "single_prompt" | "flow") => `${TEMPLATES_PATH}?type=${type}`;

/** Public sign-in pages; `?next=` never points back at one of them. */
export const AUTH_PAGES = {
  login: "/login",
  register: "/register",
  verifyEmail: "/verify-email",
  forgotPassword: "/forgot-password",
  resetPassword: "/reset-password",
  googleCallback: "/auth/google/callback",
} as const;

const AUTH_PAGE_SET = new Set<string>(Object.values(AUTH_PAGES));

/** Agent ids are `agt_` and a Crockford ULID (the contract's AgentId pattern). */
const AGENT_ID = new RegExp(scalarLimits.AgentId.pattern);
export const isAgentId = (id: string) => AGENT_ID.test(id);

/** Tabs of the single-prompt agent editor (`?tab=`); basics is the default and has no parameter. */
export type AgentEditorTab = "basics" | "voice" | "behaviour" | "tools" | "knowledge" | "quality" | "advanced";

type AgentRef = { id: string; type?: "single_prompt" | "flow" | null };

/** `/agents/:id` opens the right builder after loading the agent (routes/agents/agentRedirect.tsx). */
export const agentHomePath = (id: string) => `${AGENTS_PATH}/${id}`;
export const agentEditPath = (id: string, tab?: AgentEditorTab) =>
  tab && tab !== "basics" ? `${AGENTS_PATH}/${id}/edit?tab=${tab}` : `${AGENTS_PATH}/${id}/edit`;
export const agentFlowPath = (id: string) => `${AGENTS_PATH}/${id}/flow`;
export const agentTestingPath = (id: string) => `${AGENTS_PATH}/${id}/testing`;

/** The agent's builder: the flow canvas for flow agents, the editor otherwise. Without a type,
 * `/agents/:id` opens the right one after loading the agent. */
export function agentPath(a: AgentRef): string {
  if (!a.type) return agentHomePath(a.id);
  return a.type === "flow" ? agentFlowPath(a.id) : agentEditPath(a.id);
}

type CallsQuery = Record<string, string | readonly string[] | null | undefined>;

/** Call History's address state: list values join with commas, empty values are left out. */
function callsSearch(query: CallsQuery): URLSearchParams {
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

/** One call, opened in Call History's detail drawer. */
export const callPath = (callId: string) => callsPath({ call: callId });
export const callComparePath = (callId: string) => `${CALLS_PATH}/${callId}/compare`;
export const knowledgeBasePath = (id: string) => `${KNOWLEDGE_PATH}/${id}`;
export const datasetPath = (id: string) => `${DATASETS_PATH}/${id}`;
export const issuePath = (id: string) => `${ISSUES_PATH}/${id}`;
export const experimentPath = (id: string) => `${SIMULATIONS_PATH}/${id}`;
export const simulationRunPath = (id: string) => `${SIMULATIONS_PATH}/runs/${id}`;

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
