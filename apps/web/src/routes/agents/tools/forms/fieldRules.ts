/**
 * Inline checks for the tool editor (T095). They mirror the API's validation (tools/validation.py)
 * so Save stays disabled while a field is invalid; the server remains the authority.
 */
import type { HttpToolConfig, PressDigitConfig, ToolConfig, ToolDraft, TransferConfig } from "../../../../api/tools";
import { isMachineName, NAME_RULE } from "../../../../lib/machineName";

const E164 = /^\+[1-9]\d{6,14}$/;
const HEADER = /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$/;
const PLACEHOLDER = /\{\{\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}\}/g;

export type Errors = Record<string, string>;

export function nameError(name: string): string | null {
  if (!name) return "Enter a name.";
  if (!isMachineName(name)) return `${NAME_RULE}.`;
  if (name === "kb_search") return "kb_search is reserved for knowledge search.";
  if (name.startsWith("route_to_")) return "Names starting with route_to_ are reserved for flows.";
  return null;
}

export function e164Error(value: string | undefined, required = true): string | null {
  if (!value) return required ? "Enter the number in +E.164 form, for example +14155550100." : null;
  return E164.test(value) ? null : "Use +E.164 form: a plus, the country code and the number, for example +14155550100.";
}

/** Absolute https URL (http only in development), placeholders only in the path and query. */
export function urlError(url: string, allowHttp = false): string | null {
  if (!url.trim()) return "Enter the URL to call.";
  const probe = url.replace(PLACEHOLDER, "x");
  let parsed: URL;
  try {
    parsed = new URL(probe);
  } catch {
    return "Enter a full URL such as https://api.example.com/slots.";
  }
  if (parsed.protocol !== "https:" && !(allowHttp && parsed.protocol === "http:")) return "The URL must start with https://.";
  const host = url.split("//")[1]?.split(/[/?#]/)[0] ?? "";
  if (host.includes("{")) return "Placeholders are allowed in the path and query only.";
  if (parsed.username || parsed.password) return "Put credentials in a secret header, not in the URL.";
  return null;
}

export function parametersError(text: string): string | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return "Not valid JSON.";
  }
  if (!value || typeof value !== "object" || Array.isArray(value) || (value as { type?: unknown }).type !== "object") {
    return 'Parameters must be a JSON Schema with "type": "object".';
  }
  return null;
}

export function bodyTemplateError(text: string): string | null {
  if (!text.trim()) return null;
  try {
    JSON.parse(text);
    return null;
  } catch {
    return "Not valid JSON. Leave it empty to send the arguments as they are.";
  }
}

function transferErrors(c: TransferConfig, out: Errors) {
  if (c.routing_type === "static") {
    const e = e164Error(c.number);
    if (e) out.number = e;
  } else if (!c.routing_instructions?.trim()) {
    out.routing_instructions = "Describe how the agent picks the number.";
  }
  c.allowed_numbers.forEach((n, i) => {
    const e = e164Error(n);
    if (e) out[`allowed_numbers.${i}`] = e;
  });
  if (c.transfer_type === "warm" && !c.warm_transfer?.briefing_message?.trim()) {
    out.briefing_message = c.warm_transfer?.briefing_message_type === "prompt" ? "Write what the briefing should cover." : "Write the briefing.";
  }
  if (c.ring_timeout_s < 5 || c.ring_timeout_s > 120) out.ring_timeout_s = "Between 5 and 120 seconds.";
}

function pressErrors(c: PressDigitConfig, out: Errors) {
  if (!(c.delay_ms >= 0 && c.delay_ms <= 10000)) out.delay_ms = "Between 0 and 10,000 ms.";
  if (!(c.cooldown_ms >= 0 && c.cooldown_ms <= 60000)) out.cooldown_ms = "Between 0 and 60,000 ms.";
}

export function httpErrors(c: HttpToolConfig, texts: { parameters?: string; body?: string }, allowHttp: boolean, out: Errors) {
  const u = urlError(c.url, allowHttp);
  if (u) out.url = u;
  if (texts.parameters !== undefined) {
    const p = parametersError(texts.parameters);
    if (p) out.parameters = p;
  }
  if (texts.body !== undefined) {
    const b = bodyTemplateError(texts.body);
    if (b) out.body_template = b;
  }
  const seen = new Set<string>();
  c.headers.forEach((h, i) => {
    if (!HEADER.test(h.name)) out[`headers.${i}.name`] = "Letters, digits and - only.";
    else if (seen.has(h.name.toLowerCase())) out[`headers.${i}.name`] = "This header is listed twice.";
    seen.add(h.name.toLowerCase());
    if (h.secret && !h.value && !h.secret_ref) out[`headers.${i}.value`] = "Enter the secret value.";
    if (!h.secret && !h.value) out[`headers.${i}.value`] = "Enter a value.";
  });
  const vars = new Set<string>();
  c.response_mappings.forEach((m, i) => {
    if (!isMachineName(m.variable_name)) out[`mappings.${i}.variable_name`] = "Lowercase letters, digits and underscores.";
    else if (vars.has(m.variable_name)) out[`mappings.${i}.variable_name`] = "Mapped twice.";
    vars.add(m.variable_name);
    if (!m.json_path.trim()) out[`mappings.${i}.json_path`] = "Enter a path such as data.slots[0].time.";
  });
  if (!(c.timeout_ms >= 1000 && c.timeout_ms <= 30000)) out.timeout_ms = "Between 1 and 30 seconds.";
  if (c.speak_during_execution && !c.execution_message.trim()) out.execution_message = "Write the waiting line, or turn it off.";
}

export function draftErrors(draft: ToolDraft, texts: { parameters?: string; body?: string } = {}, allowHttp = false): Errors {
  const out: Errors = {};
  const n = nameError(draft.name);
  if (n) out.name = n;
  if (!draft.description.trim()) out.description = "Describe when the agent should use this tool.";
  const config: ToolConfig = draft.config;
  if (draft.type === "transfer_call") transferErrors(config as TransferConfig, out);
  if (draft.type === "press_digit") pressErrors(config as PressDigitConfig, out);
  if (draft.type === "http") httpErrors(config as HttpToolConfig, texts, allowHttp, out);
  return out;
}

/** Example values for the test-run arguments, from the parameters schema. */
export function exampleArguments(parameters: Record<string, unknown>): Record<string, unknown> {
  const props = (parameters.properties ?? {}) as Record<string, { type?: string; enum?: unknown[] }>;
  const out: Record<string, unknown> = {};
  for (const [key, schema] of Object.entries(props)) {
    if (schema.enum?.length) out[key] = schema.enum[0];
    else if (schema.type === "integer" || schema.type === "number") out[key] = 1;
    else if (schema.type === "boolean") out[key] = true;
    else if (key.includes("date")) out[key] = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    else out[key] = `example ${key.replace(/_/g, " ")}`;
  }
  return out;
}

export const PARAMETERS_EXAMPLE = {
  type: "object",
  properties: {
    date: { type: "string", description: "Requested date, YYYY-MM-DD" },
    doctor_name: { type: "string", description: "Doctor the caller asked for" },
  },
  required: ["date"],
};
