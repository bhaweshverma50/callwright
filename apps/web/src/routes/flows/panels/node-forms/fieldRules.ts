/**
 * Inline checks for node panels (FR-045, T104). They mirror the API validator (flows/validation.py)
 * so problems show next to the field while typing; the same checks block publishing on the server.
 */
import { e164Error, urlError } from "../../../agents/tools/forms/fieldRules";

export { e164Error, urlError };

const FIELD = /^[a-z][a-z0-9_]{0,39}$/;
const CATEGORY = /^[A-Za-z0-9][A-Za-z0-9 _-]{0,59}$/;
const REASON = /^[a-z_]{1,40}$/;
const PLACEHOLDER = /\{\{\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}\}/g;

export function rangeError(value: number, min: number, max: number, unit = ""): string | null {
  if (!Number.isFinite(value) || !Number.isInteger(value)) return `Enter a whole number from ${min} to ${max}${unit}.`;
  if (value < min || value > max) return `Use a value from ${min} to ${max}${unit}.`;
  return null;
}

export function maxRoundsError(value: number): string | null {
  return rangeError(value, 1, 20);
}

export function timeoutError(ms: number): string | null {
  return rangeError(Math.round(ms / 1000), 1, 30, " seconds");
}

/** JSON syntax with the line of the problem, placeholders allowed as values. */
export function jsonError(text: string, { required = false } = {}): string | null {
  if (!text.trim()) return required ? "Enter JSON." : null;
  const problem = scanJson(text.replace(PLACEHOLDER, (m) => "0".padEnd(m.length, " ")));
  if (!problem) return null;
  const line = text.slice(0, problem.at).split("\n").length;
  return `Line ${line}: ${problem.reason}.`;
}

/** A small JSON scanner that says where the first problem is (JSON.parse messages vary by browser). */
function scanJson(src: string): { at: number; reason: string } | null {
  let i = 0;
  const ws = () => {
    while (i < src.length && " \t\n\r".includes(src[i]!)) i++;
  };
  const fail = (reason: string): never => {
    throw { at: Math.min(i, src.length), reason };
  };
  const literal = (word: string) => {
    if (src.startsWith(word, i)) i += word.length;
    else fail("Unexpected text");
  };
  const string = () => {
    i++;
    while (i < src.length && src[i] !== '"') {
      if (src[i] === "\n") fail("Unclosed string");
      i += src[i] === "\\" ? 2 : 1;
    }
    if (i >= src.length) fail("Unclosed string");
    i++;
  };
  const number = () => {
    const m = /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?/.exec(src.slice(i));
    if (!m) fail("Unexpected text");
    i += m![0].length;
  };
  const value = (): void => {
    ws();
    const c = src[i];
    if (c === "{") {
      i++;
      ws();
      if (src[i] === "}") return void i++;
      for (;;) {
        ws();
        if (src[i] !== '"') fail(src[i] === "}" ? "Trailing comma" : "Expected a quoted key");
        string();
        ws();
        if (src[i] !== ":") fail("Expected a colon");
        i++;
        value();
        ws();
        if (src[i] === ",") {
          i++;
          continue;
        }
        if (src[i] === "}") return void i++;
        fail("Expected a comma or a closing brace");
      }
    }
    if (c === "[") {
      i++;
      ws();
      if (src[i] === "]") return void i++;
      for (;;) {
        value();
        ws();
        if (src[i] === ",") {
          i++;
          ws();
          if (src[i] === "]") fail("Trailing comma");
          continue;
        }
        if (src[i] === "]") return void i++;
        fail("Expected a comma or a closing bracket");
      }
    }
    if (c === '"') return string();
    if (c === "t") return literal("true");
    if (c === "f") return literal("false");
    if (c === "n") return literal("null");
    if (c === "-" || (c !== undefined && c >= "0" && c <= "9")) return number();
    fail(c === undefined ? "Unexpected end" : "Unexpected text");
  };
  try {
    value();
    ws();
    if (i < src.length) fail("Unexpected text after the value");
    return null;
  } catch (e) {
    return e as { at: number; reason: string };
  }
}

export function categoryNameError(name: string, others: string[]): string | null {
  if (!name.trim()) return "Enter a category name.";
  if (!CATEGORY.test(name)) return "Use 1 to 60 letters, digits, spaces, hyphens or underscores.";
  if (others.some((o) => o.toLowerCase() === name.toLowerCase())) return `${name} is already a category.`;
  return null;
}

export function fieldNameError(name: string, others: string[]): string | null {
  if (!FIELD.test(name)) return "Use lowercase letters, digits and underscores, starting with a letter.";
  if (others.includes(name)) return `${name} is already used.`;
  return null;
}

/** "Customer Name" -> "customer_name" (FR-056), shown before the variable is added. */
export function toVariableName(text: string): string {
  let slug = text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (/^\d/.test(slug)) slug = `v_${slug}`;
  return slug.slice(0, 40);
}

export function reasonError(reason: string): string | null {
  return REASON.test(reason) ? null : "Use lowercase letters and underscores, up to 40 characters.";
}
