import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "./Button";
import { cn } from "./cn";
import { Select } from "./Select";
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
  /** Highlighted row (its detail is shown in the inspector). */
  selectedKey?: string | null;
  /** Hover or focus previews a row in the inspector. */
  onRowPreview?: (row: T) => void;
  className?: string;
}

/**
 * Dense data table: sentence-case headers on a recessed band, single hairlines, numeric columns
 * right aligned in Geist Mono, a full-row tint on the selected row.
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  loading,
  skeletonRows = 8,
  empty,
  caption,
  stale,
  selectedKey,
  onRowPreview,
  className,
}: TableProps<T>) {
  const showSkeleton = loading && !rows;
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-[13px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-line bg-surface-2/70">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={c.width ? { width: c.width } : undefined}
                className={cn(
                  "h-9 whitespace-nowrap px-3 text-[12px] font-medium text-fg-3 first:pl-5 last:pr-5",
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
                  <td key={c.key} className={cn("h-11 px-3 first:pl-5 last:pr-5", c.hideOnNarrow && "hidden md:table-cell")}>
                    <Skeleton className={cn("h-3", c.numeric ? "ml-auto w-14" : "w-3/4")} />
                  </td>
                ))}
              </tr>
            ))}
          {!showSkeleton &&
            rows?.map((r) => {
              const key = rowKey(r);
              const selected = selectedKey === key;
              return (
                <tr
                  key={key}
                  aria-selected={selectedKey !== undefined ? selected : undefined}
                  onMouseEnter={onRowPreview ? () => onRowPreview(r) : undefined}
                  className={cn(
                    "relative border-b border-line transition-colors duration-150 last:border-0 hover:bg-accent-soft/35",
                    selected && "bg-accent-soft/60",
                  )}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "h-11 px-3 align-middle text-fg first:pl-5 last:pr-5",
                        (c.align === "right" || c.numeric) && "text-right",
                        c.numeric && "font-mono text-[13px] tnum",
                        c.hideOnNarrow && "hidden md:table-cell",
                      )}
                    >
                      {c.cell(r)}
                    </td>
                  ))}
                </tr>
              );
            })}
        </tbody>
      </table>
      {!showSkeleton && rows?.length === 0 && empty}
    </div>
  );
}

/** Page sizes every paged list offers; lists open on the smallest so the pager stays in reach. */
export const LIST_PAGE_SIZES = [10, 20, 50] as const;
export const DEFAULT_LIST_PAGE_SIZE = LIST_PAGE_SIZES[0];

/**
 * The page size a viewer picked for one list, remembered in this browser. Falls back to the default
 * when storage is blocked or holds something that is not an offered size.
 */
export function usePageSize(list: string, sizes: readonly number[] = LIST_PAGE_SIZES): [number, (size: number) => void] {
  const key = `cw.pageSize.${list}`;
  const [size, setSize] = useState(() => {
    try {
      const n = Number(localStorage.getItem(key));
      return sizes.includes(n) ? n : sizes[0]!;
    } catch {
      return sizes[0]!;
    }
  });
  const set = (n: number) => {
    setSize(n);
    try {
      localStorage.setItem(key, String(n));
    } catch {
      /* storage blocked: keep it for this visit only */
    }
  };
  return [size, set];
}

export interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** Offer a rows-per-page picker; changing it should also return to page 1. */
  onPageSizeChange?: (size: number) => void;
  pageSizes?: readonly number[];
  /** What is being counted, plural ("transactions"). */
  noun?: string;
  className?: string;
}

/**
 * "41 to 60 of 312 transactions", an optional rows-per-page picker, and previous and next buttons.
 * Goes at the foot of a list; put {@link PagerCompact} in the list's header so long pages can be
 * turned without scrolling.
 */
export function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  onPageSizeChange,
  pageSizes = LIST_PAGE_SIZES,
  noun = "rows",
  className,
}: PaginationProps) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav aria-label="Pagination" className={cn("flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-3", className)}>
      <p className="text-[13px] text-fg-3">
        <span className="font-mono tnum">{from.toLocaleString()}</span> to <span className="font-mono tnum">{to.toLocaleString()}</span> of{" "}
        <span className="font-mono tnum">{total.toLocaleString()}</span> {noun}
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {onPageSizeChange && (
          <label className="flex items-center gap-2 text-[13px] text-fg-3">
            Rows per page
            <Select
              size="sm"
              aria-label="Rows per page"
              className="w-[76px]"
              value={String(pageSize)}
              onValueChange={(v) => onPageSizeChange(Number(v))}
              options={pageSizes.map((n) => ({ value: String(n), label: String(n) }))}
            />
          </label>
        )}
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPageChange(page - 1)} icon={<ChevronLeft aria-hidden />}>
            Previous
          </Button>
          <span className="font-mono text-[12px] text-fg-2 tnum" aria-current="page">
            {page} / {Math.max(1, totalPages)}
          </span>
          <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
            Next
            <ChevronRight aria-hidden />
          </Button>
        </div>
      </div>
    </nav>
  );
}

/** The header pager: "1-10 of 34" with icon-only previous and next. Hidden when everything fits on one page. */
export function PagerCompact({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  className,
}: Pick<PaginationProps, "page" | "totalPages" | "total" | "pageSize" | "onPageChange" | "className">) {
  if (totalPages <= 1) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav aria-label="Pagination, top" className={cn("flex items-center gap-1", className)}>
      <span className="mr-1 whitespace-nowrap font-mono text-[12px] text-fg-3 tnum">
        {from}-{to} of {total.toLocaleString()}
      </span>
      <Button size="sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        <ChevronLeft aria-hidden />
      </Button>
      <Button size="sm" variant="ghost" aria-label="Next page" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
        <ChevronRight aria-hidden />
      </Button>
    </nav>
  );
}
