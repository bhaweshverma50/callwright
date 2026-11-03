import { ChevronsUpDown } from "lucide-react";
import { useState } from "react";
import { cn } from "../../../components";
import type { DiffLine } from "./lineDiff";

const CONTEXT = 2;

type Block = { kind: "line"; line: DiffLine; n: number } | { kind: "fold"; lines: DiffLine[]; start: number };

/** Groups long runs of unchanged lines into folds, keeping two lines of context around changes. */
function blocks(lines: DiffLine[]): Block[] {
  const out: Block[] = [];
  const keep = lines.map((l, i) => l.kind !== "same" || lines.slice(Math.max(0, i - CONTEXT), i + CONTEXT + 1).some((x) => x.kind !== "same"));
  let i = 0;
  while (i < lines.length) {
    if (keep[i]) {
      out.push({ kind: "line", line: lines[i]!, n: i });
      i++;
      continue;
    }
    const start = i;
    while (i < lines.length && !keep[i]) i++;
    const run = lines.slice(start, i);
    if (run.length <= 2) run.forEach((line, k) => out.push({ kind: "line", line, n: start + k }));
    else out.push({ kind: "fold", lines: run, start });
  }
  return out;
}

/**
 * Line-by-line difference: added lines on a success tint with a plus, removed lines on a danger
 * tint with a minus and struck through, unchanged runs folded. Colour is never the only signal.
 */
export function DiffView({ lines, className }: { lines: DiffLine[]; className?: string }) {
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  return (
    <div className={cn("py-1 font-sans text-[12.5px] leading-relaxed", className)} role="table" aria-label="Line changes">
      {blocks(lines).map((b) =>
        b.kind === "fold" && !open.has(b.start) ? (
          // A table only holds rows, so the fold button sits in a row of its own.
          <div key={`f${b.start}`} role="row">
            <div role="cell" aria-colspan={2}>
              <button
                type="button"
                onClick={() => setOpen((s) => new Set(s).add(b.start))}
                className="flex w-full cursor-pointer items-center gap-2 bg-surface-2/60 px-4 py-1 text-left text-[12px] text-fg-3 hover:text-fg focus-visible:outline-2 focus-visible:outline-ring"
              >
                <ChevronsUpDown className="size-3.5" aria-hidden />
                {b.lines.length} unchanged lines
              </button>
            </div>
          </div>
        ) : (
          (b.kind === "fold" ? b.lines.map((line, k) => ({ line, n: b.start + k })) : [{ line: b.line, n: b.n }]).map(({ line, n }) => (
            <div
              key={n}
              role="row"
              className={cn(
                "grid grid-cols-[20px_minmax(0,1fr)] gap-1 px-3",
                line.kind === "add" && "bg-success-soft/70 text-fg",
                line.kind === "remove" && "bg-danger-soft/60 text-fg-2",
                line.kind === "same" && "text-fg-2",
              )}
            >
              <span
                role="cell"
                aria-label={line.kind === "add" ? "Added" : line.kind === "remove" ? "Removed" : "Unchanged"}
                className={cn(
                  "select-none text-center font-mono",
                  line.kind === "add" ? "text-success-text" : line.kind === "remove" ? "text-danger-text" : "text-fg-3",
                )}
              >
                {line.kind === "add" ? "+" : line.kind === "remove" ? "-" : ""}
              </span>
              <span
                role="cell"
                className={cn(
                  "min-w-0 whitespace-pre-wrap break-words py-px",
                  line.kind === "remove" && line.text.trim() && "line-through decoration-danger-text/40",
                )}
              >
                {line.text || " "}
              </span>
            </div>
          ))
        ),
      )}
    </div>
  );
}
