/**
 * Keyed diff between two configs (research R12): list items are matched by their key, not their
 * position (variables by name, pronunciation by word ignoring case, tool and knowledge ids by
 * value), so reordering is not a change and an edit reads as an edit of that item.
 */
import type { VersionChange } from "../../api/agents";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

const KEYED: Record<string, (item: Obj) => string> = {
  "/dynamic_variables": (i) => String(i.name),
  "/advanced/pronunciation": (i) => String(i.word).trim().toLowerCase(),
};
const VALUE_LISTS = new Set(["/tool_ids", "/kb_ids"]);
const SKIP = new Set(["/tools", "/schema_version", "/type"]);

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function diffConfigs(from: unknown, to: unknown, path = ""): VersionChange[] {
  if (SKIP.has(path)) return [];
  if (same(from, to)) return [];
  const keyOf = KEYED[path];
  if (keyOf && Array.isArray(from) && Array.isArray(to)) {
    const out: VersionChange[] = [];
    const a = new Map((from as Obj[]).map((i) => [keyOf(i), i]));
    const b = new Map((to as Obj[]).map((i) => [keyOf(i), i]));
    for (const [k, v] of b) {
      const old = a.get(k);
      if (!old) out.push({ op: "add", path: `${path}[${k}]`, new: v });
      else out.push(...diffConfigs(old, v, `${path}[${k}]`));
    }
    for (const [k, v] of a) if (!b.has(k)) out.push({ op: "remove", path: `${path}[${k}]`, old: v });
    return out;
  }
  if (VALUE_LISTS.has(path) && Array.isArray(from) && Array.isArray(to)) {
    const out: VersionChange[] = [];
    for (const v of to) if (!from.includes(v)) out.push({ op: "add", path: `${path}[${v}]`, new: v });
    for (const v of from) if (!to.includes(v)) out.push({ op: "remove", path: `${path}[${v}]`, old: v });
    return out;
  }
  if (isObj(from) && isObj(to)) {
    const keys = [...new Set([...Object.keys(from), ...Object.keys(to)])];
    return keys.flatMap((k) => {
      const p = `${path}/${k}`;
      if (SKIP.has(p)) return [];
      if (!(k in from) || from[k] === undefined) return to[k] === undefined || to[k] === null ? [] : [{ op: "add" as const, path: p, new: to[k] }];
      if (!(k in to) || to[k] === undefined) return from[k] === null ? [] : [{ op: "remove" as const, path: p, old: from[k] }];
      return diffConfigs(from[k], to[k], p);
    });
  }
  return [{ op: "replace", path: path || "/", old: from, new: to }];
}
