import { CaretLeft, CaretRight } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Button } from "./Button";
import { cn } from "./cn";
import { Skeleton } from "./Skeleton";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Numbers right-align and use tabular mono figures. */
  align?: "left" | "right";
  numeric?: boolean;
  width?: string;
  /** Hidden below the md breakpoint so tables stay readable on narrow screens. */
  hideOnNarrow?: boolean;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  loading?: boolean;
  /** Rows shown while loading the first page. */
  skeletonRows?: number;
  empty?: ReactNode;
  caption?: string;
  /** Dims rows while the next page loads (keepPreviousData). */
  stale?: boolean;
  className?: string;
}

/**
 * Dense data table. Headers are mono labels, rows separated by single hairlines, numeric
 * columns right-aligned with tabular figures so amounts line up.
 */
export function Table<T>({ columns, rows, rowKey, loading, skeletonRows = 8, empty, caption, stale, className }: TableProps<T>) {
  const showSkeleton = loading && !rows;
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-[13px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-line">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={c.width ? { width: c.width } : undefined}
                className={cn(
                  "h-8 whitespace-nowrap px-3 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-3 first:pl-4 last:pr-4",
                  c.align === "right" || c.numeric ? "text-right" : "text-left",
                  c.hideOnNarrow && "hidden md:table-cell",
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={cn("transition-opacity", stale && "opacity-60")}>
          {showSkeleton &&
            Array.from({ length: skeletonRows }, (_, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                {columns.map((c) => (
                  <td key={c.key} className={cn("h-10 px-3 first:pl-4 last:pr-4", c.hideOnNarrow && "hidden md:table-cell")}>
                    <Skeleton className={cn("h-3", c.numeric ? "ml-auto w-14" : "w-3/4")} />
                  </td>
                ))}
              </tr>
            ))}
          {!showSkeleton &&
            rows?.map((r) => (
              <tr key={rowKey(r)} className="border-b border-line transition-colors last:border-0 hover:bg-surface-2">
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      "h-10 px-3 align-middle text-fg first:pl-4 last:pr-4",
                      (c.align === "right" || c.numeric) && "text-right",
                      c.numeric && "font-mono text-[12.5px] tnum",
                      c.hideOnNarrow && "hidden md:table-cell",
                    )}
                  >
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
      {!showSkeleton && rows?.length === 0 && empty}
    </div>
  );
}

export interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** What is being counted, plural ("transactions"). */
  noun?: string;
  className?: string;
}

/** "41 to 60 of 312 transactions" with previous and next buttons. */
export function Pagination({ page, totalPages, total, pageSize, onPageChange, noun = "rows", className }: PaginationProps) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav aria-label="Pagination" className={cn("flex items-center justify-between gap-4 px-4 py-2.5", className)}>
      <p className="font-mono text-[11.5px] text-fg-3 tnum">
        {from.toLocaleString()} to {to.toLocaleString()} of {total.toLocaleString()} {noun}
      </p>
      <div className="flex items-center gap-1.5">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPageChange(page - 1)} icon={<CaretLeft aria-hidden />}>
          Previous
        </Button>
        <span className="font-mono text-[11.5px] text-fg-2 tnum" aria-current="page">
          {page} / {Math.max(1, totalPages)}
        </span>
        <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          Next
          <CaretRight aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
