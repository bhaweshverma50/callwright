/** Machine names for analysis variables and custom checks (007 FR-001, FR-045, FR-044). */

export const MACHINE_NAME_RE = /^[a-z][a-z0-9_]{0,63}$/;
export const NAME_RULE = "Use lowercase letters, digits and underscores, starting with a letter";

/**
 * What the operator typed, as a valid name: lowercase, spaces and punctuation to underscores,
 * repeated underscores collapsed, leading digits or underscores removed, at most 64 characters.
 * Returns "" when nothing usable is left (for example only punctuation).
 *
 *   toVariableName("Customer Mood") === "customer_mood"
 */
export function toVariableName(input: string): string {
  const name = input
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[0-9_]+/, "")
    .slice(0, 64)
    .replace(/_+$/, "");
  return MACHINE_NAME_RE.test(name) ? name : "";
}
