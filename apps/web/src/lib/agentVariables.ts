import { schemaLimits } from "./contract.gen";
/**
 * Dynamic variable rules (spec 002 FR-008): names start with a letter or underscore and contain
 * only letters, digits and underscores (max 64), at most 50 per agent, built-in names reserved.
 * `{{ name }}` placeholders in the prompt and greeting are found with any inner spacing; malformed
 * ones (`{{ name`, `{{1abc}}`) are reported and never added.
 */
export const VARIABLE_NAME = new RegExp(schemaLimits.DynamicVariable.name.pattern);
export const MAX_VARIABLES = schemaLimits.AgentConfig.dynamic_variables.maxItems;
export const RESERVED_VARIABLES = schemaLimits.DynamicVariable.name["x-reserved"];

export const isReserved = (name: string) => (RESERVED_VARIABLES as readonly string[]).includes(name);

export interface PlaceholderScan {
  /** Valid, non-reserved names in order of first appearance. */
  names: string[];
  /** Built-in names used in the text (allowed, never declared). */
  builtins: string[];
  /** Placeholders that are not valid names, as written (`{{1abc}}`, `{{ name`). */
  invalid: string[];
}

export function scanPlaceholders(...texts: (string | null | undefined)[]): PlaceholderScan {
  const names: string[] = [];
  const builtins: string[] = [];
  const invalid: string[] = [];
  for (const text of texts) {
    if (!text) continue;
    // Closed placeholders first, then any "{{" that never closes.
    const closed = /\{\{([^{}]*)\}\}/g;
    let m: RegExpExecArray | null;
    while ((m = closed.exec(text))) {
      const inner = (m[1] ?? "").trim();
      if (VARIABLE_NAME.test(inner)) {
        if (isReserved(inner)) {
          if (!builtins.includes(inner)) builtins.push(inner);
        } else if (!names.includes(inner)) names.push(inner);
      } else if (!invalid.includes(m[0])) invalid.push(m[0]);
    }
    const stripped = text.replace(closed, "");
    const open = /\{\{\s*([^\s{}]*)/g;
    while ((m = open.exec(stripped))) {
      const raw = m[0].trim();
      if (!invalid.includes(raw)) invalid.push(raw);
    }
  }
  return { names, builtins, invalid };
}

/** Why a hand-typed variable name is refused, or null when it is fine. */
export function variableNameProblem(name: string, existing: string[] = []): string | null {
  if (!name) return "Enter a name.";
  if (!VARIABLE_NAME.test(name)) return "Use letters, digits and underscores, starting with a letter or underscore (64 characters at most).";
  if (isReserved(name)) return `${name} is a built-in variable; use it in the prompt without declaring it.`;
  if (existing.includes(name)) return `${name} is already in the list.`;
  if (existing.length >= MAX_VARIABLES) return `An agent can have at most ${MAX_VARIABLES} variables.`;
  return null;
}
