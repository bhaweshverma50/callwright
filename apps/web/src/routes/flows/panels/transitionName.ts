/**
 * Transition name derivation (FR-044): the TypeScript copy of services/api/app/flows/transitions.py,
 * kept identical by the shared vectors in services/api/tests/unit/flows/fixtures/transition_names.json.
 */
const PREFIX = "route_to_";
const MAX_SLUG = 48;

export function transitionSlug(label: string | null | undefined): string {
  let text = (label ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (text.startsWith(PREFIX)) text = text.slice(PREFIX.length);
  else if (text === PREFIX.replace(/_+$/, "")) text = "";
  return text.slice(0, MAX_SLUG).replace(/^_+|_+$/g, "");
}

/** The function name the model sees, or null when the label has no letter or digit. */
export function transitionName(label: string | null | undefined, override?: string | null): string | null {
  if (override) return override;
  const slug = transitionSlug(label);
  return slug ? `${PREFIX}${slug}` : null;
}

export function transitionDescription(targetLabel: string, condition: string | null | undefined): string {
  const c = (condition ?? "").trim();
  return c ? `Go to ${targetLabel}. Use when: ${c}` : `Go to ${targetLabel}.`;
}
