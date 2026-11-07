/**
 * Machine names: tool names, analysis variables, custom check names (64 characters) and flow
 * task and extraction fields (40 characters). Lowercase letters, digits and underscores, starting
 * with a letter. The API applies the same rule; these checks only point at the field early.
 */

export const MACHINE_NAME_MAX = 64;
export const FLOW_FIELD_NAME_MAX = 40;
export const NAME_RULE = "Use lowercase letters, digits and underscores, starting with a letter";

export function isMachineName(name: string, max = MACHINE_NAME_MAX): boolean {
  return name.length <= max && /^[a-z][a-z0-9_]*$/.test(name);
}

/**
 * What the operator typed, as a valid name: accents dropped, lowercase, spaces and punctuation to
 * single underscores, a leading digit prefixed with `v_`, at most `max` characters. Returns "" when
 * nothing usable is left (for example only punctuation).
 *
 *   toMachineName("Customer Mood") === "customer_mood"
 */
export function toMachineName(input: string, max = MACHINE_NAME_MAX): string {
  let name = input
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (/^\d/.test(name)) name = `v_${name}`;
  name = name.slice(0, max).replace(/_+$/, "");
  return isMachineName(name, max) ? name : "";
}
