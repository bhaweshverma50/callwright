/**
 * Test categories (FR-032): a colour chip per category, listed alphabetically everywhere, and the
 * rule for which category a new case starts in.
 */
import type { TestCategory, TestResult } from "../../../api/testing";
import { Badge, cn, type SelectOption, type Tone } from "../../../components";

export const ALL_CATEGORIES = "__all";

export function CategoryDot({ color, className }: { color: string; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2.5 shrink-0 rounded-full", className)} style={{ background: color }} />;
}

/** Category name with its colour chip. Unknown slugs (a deleted category) read as the slug. */
export function CategoryLabel({ slug, categories, className }: { slug: string; categories: TestCategory[] | undefined; className?: string }) {
  const c = categories?.find((x) => x.slug === slug);
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5 text-[12.5px] text-fg-2", className)}>
      <CategoryDot color={c?.color ?? "var(--text-3)"} />
      <span className="truncate">{c?.name ?? slug}</span>
    </span>
  );
}

export const sortCategories = (list: TestCategory[]) => list.slice().sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

export function categoryOptions(list: TestCategory[] | undefined): SelectOption[] {
  return sortCategories(list ?? []).map((c) => ({
    value: c.slug,
    label: (
      <span className="flex items-center gap-2">
        <CategoryDot color={c.color} />
        {c.name}
      </span>
    ),
  }));
}

/** A new case starts in the filtered category, otherwise the first category listed. */
export function initialCategory(list: TestCategory[] | undefined, filtered: string | null): string {
  const sorted = sortCategories(list ?? []);
  if (filtered && sorted.some((c) => c.slug === filtered)) return filtered;
  return sorted[0]?.slug ?? "";
}

const STATUS: Record<"passed" | "failed" | "error", { label: string; tone: Tone }> = {
  passed: { label: "Passed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  error: { label: "Error", tone: "warning" },
};

export function TestStatusBadge({ status }: { status: TestResult["status"] | undefined }) {
  if (!status) return <Badge tone="neutral">Not run</Badge>;
  const s = STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
