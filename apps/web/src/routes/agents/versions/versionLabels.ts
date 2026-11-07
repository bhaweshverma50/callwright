/**
 * Readable names and values for AgentConfig paths in version compare, the error summary and
 * warnings (T061, FR-025): fields are named by the editor's own labels (config/fields.ts), never as
 * JSON pointers. Keyed list items read as "Variable order_id" or "Pronunciation of SQL".
 */
import { formatMs, formatMultiplier, formatPercentOfNormal, formatSeconds } from "../editor/formatters";
import { CONFIG_FIELDS } from "../config/fields";

/** Version snapshot entries that are not editor fields. */
const SNAPSHOT_LABELS: Record<string, string> = {
  "/schema_version": "Format version",
  "/type": "Agent type",
  "/tool_ids": "Tools",
  "/kb_ids": "Knowledge bases",
  "/flow": "Flow",
  "/evals": "Quality checks",
  "/tools": "Tools",
  "/knowledge": "Knowledge bases",
  "/note": "Version note",
};

const pathLabel = (path: string): string | undefined => CONFIG_FIELDS[path]?.label ?? SNAPSHOT_LABELS[path];

const KEYED = /^(\/dynamic_variables|\/advanced\/pronunciation|\/tool_ids|\/kb_ids|\/tools|\/knowledge)\[([^\]]*)\](\/.*)?$/;

/** Readable name for a JSON pointer, including keyed list items. ``names`` maps tool and
 * knowledge base ids to their names (from the snapshot blocks in the same diff). */
export function labelFor(path: string, names?: ReadonlyMap<string, string>): string {
  const k = KEYED.exec(path);
  if (k) {
    const [, list, key, rest] = k;
    if (list === "/dynamic_variables")
      return rest === "/default" ? `Default for ${key}` : rest === "/description" ? `Description of ${key}` : `Variable ${key}`;
    if (list === "/advanced/pronunciation") return rest === "/replacement" ? `Pronunciation of "${key}"` : `Word "${key}"`;
    const kind = list === "/tool_ids" || list === "/tools" ? "Tool" : "Knowledge base";
    const name = (key && names?.get(key)) ?? key;
    return rest ? `${kind} ${name}: ${humanize(rest.split("/").pop() ?? "")}` : `${kind} ${name}`;
  }
  return pathLabel(path) ?? pathLabel(path.replace(/\/\d+$/, "")) ?? path.split("/").filter(Boolean).pop()?.replace(/_/g, " ") ?? path;
}

/** Long text gets a line diff in compare instead of old and new values side by side. */
export const isLongText = (path: string) => CONFIG_FIELDS[path]?.long === true;

/** A value as people read it in compare ("1.5 s", "On", "None"). ``languages`` maps language
 * codes to their catalog labels for the caller languages list. */
export function formatValue(path: string, v: unknown, languages?: ReadonlyMap<string, string>): string {
  if (v === null || v === undefined || v === "") return "None";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (typeof v === "number") {
    if (path.endsWith("_ms")) return formatMs(v);
    if (path.endsWith("_s")) return formatSeconds(v);
    if (path === "/tts/speed") return formatMultiplier(v);
    if (path.endsWith("volume")) return formatPercentOfNormal(v);
    return String(v);
  }
  if (typeof v === "string") {
    if (path === "/start_speaker") return v === "user" ? "Caller speaks first" : "Agent speaks first";
    if (path === "/stt/model" && !v) return "Auto";
    return v;
  }
  if (path === "/advanced/language_switching/languages" && Array.isArray(v))
    return v.length ? v.map((c) => languages?.get(String(c)) ?? String(c)).join(", ") : "All supported languages";
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("provider" in o && "model" in o) return `${o.provider} / ${o.model ?? "Auto"}`;
    if ("name" in o) return o.default ? `${o.name} (default ${o.default})` : String(o.name);
    if ("word" in o) return `${o.word} said as ${o.replacement}`;
    if ("kind" in o) return String(o.id ?? o.key);
    return JSON.stringify(v);
  }
  return String(v);
}

/** "cooldown_ms" -> "Cooldown". Unit suffixes are dropped because values carry their unit. */
export function humanize(key: string): string {
  const words = key.replace(/_(ms|s|usd)$/, "").replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const TOOL_TYPES: Record<string, string> = {
  end_call: "End call",
  transfer_call: "Transfer call",
  press_digit: "Press keypad digits",
  http: "HTTP request",
};

/** Fields of an object as label and readable value, skipping ids and empty values. Nested
 * objects are flattened one level ("Delay: 1 s"). */
export function objectFields(path: string, value: Record<string, unknown>): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = [];
  for (const [key, v] of Object.entries(value)) {
    if (v === null || v === undefined || v === "" || key.endsWith("_id") || key === "id") continue;
    if (typeof v === "object" && !Array.isArray(v)) {
      out.push(...objectFields(`${path}/${key}`, v as Record<string, unknown>));
      continue;
    }
    if (key === "type" && typeof v === "string" && v in TOOL_TYPES) {
      out.push({ label: "Type", value: TOOL_TYPES[v] ?? v });
      continue;
    }
    const shown = Array.isArray(v)
      ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ")
      : formatValue(`${path}/${key}`, v);
    out.push({ label: humanize(key), value: shown });
  }
  return out;
}

type Change = { op: "add" | "remove" | "replace"; path: string; old?: unknown; new?: unknown };
const SNAPSHOT_LISTS = { "/tools": ["tool_id", "/tool_ids"], "/knowledge": ["kb_id", "/kb_ids"] } as const;

/** Changes as people read them: whole tool and knowledge lists split into one change per item,
 * and the id-only entries dropped when the same item's full change is shown. Also returns the id
 * to name map for labels. */
export function readableChanges<C extends Change>(changes: C[]): { changes: C[]; names: Map<string, string> } {
  const names = new Map<string, string>();
  const note = (item: unknown, key: string) => {
    if (item && typeof item === "object") {
      const o = item as Record<string, unknown>;
      if (typeof o[key] === "string") names.set(o[key], typeof o.name === "string" ? o.name : (o[key] as string));
    }
  };
  const out: C[] = [];
  const covered = new Set<string>();
  for (const c of changes) {
    const entry = Object.entries(SNAPSHOT_LISTS).find(([list]) => c.path === list || c.path.startsWith(`${list}[`));
    if (!entry) {
      out.push(c);
      continue;
    }
    const [list, [key, idList]] = entry;
    if (c.path !== list) {
      note(c.old, key);
      note(c.new, key);
      const id = /\[([^\]]*)\]/.exec(c.path)?.[1];
      if (id) covered.add(`${idList}[${id}]`);
      out.push(c);
      continue;
    }
    // The whole list was added, removed or replaced: one change per item, matched by id.
    const items = (v: unknown) => new Map((Array.isArray(v) ? v : []).map((it) => [String((it as Record<string, unknown>)[key]), it]));
    const before = items(c.old);
    const after = items(c.new);
    for (const [id, it] of before) {
      note(it, key);
      covered.add(`${idList}[${id}]`);
      if (!after.has(id)) out.push({ ...c, op: "remove", path: `${list}[${id}]`, old: it, new: undefined });
      else if (JSON.stringify(it) !== JSON.stringify(after.get(id)))
        out.push({ ...c, op: "replace", path: `${list}[${id}]`, old: it, new: after.get(id) });
    }
    for (const [id, it] of after) {
      note(it, key);
      covered.add(`${idList}[${id}]`);
      if (!before.has(id)) out.push({ ...c, op: "add", path: `${list}[${id}]`, old: undefined, new: it });
    }
  }
  return { changes: out.filter((c) => !covered.has(c.path)), names };
}
