/**
 * Line-by-line difference for long text (prompts, greetings) in version compare, the prompt
 * assistant (002 US3.2, US6.1) and issue fixes (009 T033). A longest-common-subsequence walk over
 * lines; very long texts fall back to a plain before and after so the browser never stalls.
 */
export type DiffLine = { kind: "same" | "add" | "remove"; text: string };

const MAX_CELLS = 4_000_000;

export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  if (a.length * b.length > MAX_CELLS) {
    return [...a.map((text) => ({ kind: "remove" as const, text })), ...b.map((text) => ({ kind: "add" as const, text }))];
  }
  const n = a.length;
  const m = b.length;
  const lcs: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i]![j] = a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i]! });
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      out.push({ kind: "remove", text: a[i++]! });
    } else {
      out.push({ kind: "add", text: b[j++]! });
    }
  }
  while (i < n) out.push({ kind: "remove", text: a[i++]! });
  while (j < m) out.push({ kind: "add", text: b[j++]! });
  return out;
}

/** Counts for a summary line ("4 lines added, 2 removed"). */
export function diffStats(lines: DiffLine[]) {
  return { added: lines.filter((l) => l.kind === "add").length, removed: lines.filter((l) => l.kind === "remove").length };
}
