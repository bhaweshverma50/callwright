import { CircleAlert, CircleCheck, ListChecks, TriangleAlert } from "lucide-react";
import type { ConfigIssue } from "../../../api/agents";
import { InfoTip, Skeleton, cn } from "../../../components";
import { labelFor } from "../versions/versionLabels";

/**
 * Checks in the inspector (FR-014, FR-016): publish blockers (save works, publishing does not) and
 * warnings (nothing blocked), each linked to its field. Blocking errors live inline and in the
 * error summary instead.
 */
export function ChecksCard({
  blockers,
  warnings,
  loading,
  onJump,
}: {
  blockers: ConfigIssue[];
  warnings: ConfigIssue[];
  loading: boolean;
  onJump: (pointer: string) => void;
}) {
  const items = [...blockers.map((b) => ({ ...b, kind: "blocker" as const })), ...warnings.map((w) => ({ ...w, kind: "warning" as const }))];
  return (
    <section aria-labelledby="checks-title" className="rounded-panel border border-line bg-surface shadow-1">
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex items-start gap-2.5">
          <ListChecks className="mt-0.5 size-4 text-fg-3" aria-hidden />
          <div className="flex flex-col gap-0.5">
            <h2 id="checks-title" className="text-[14px] font-semibold text-fg">
              Checks
            </h2>
            <p className="text-[12.5px] text-fg-3">Things to review before this agent goes live.</p>
          </div>
        </div>
        <InfoTip label="About checks" side="left">
          Warnings never block saving. Publish blockers let you save but stop the version from going live, for example a component without a price.
        </InfoTip>
      </header>
      {loading && items.length === 0 ? (
        <div className="flex flex-col gap-2 px-5 py-4">
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      ) : items.length === 0 ? (
        <p className="flex items-center gap-2 px-5 py-4 text-[13px] text-fg-2">
          <CircleCheck className="size-4 text-success-text" aria-hidden /> No problems found.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((it) => (
            <li key={`${it.kind}${it.pointer}${it.code}`}>
              <button
                type="button"
                onClick={() => onJump(it.pointer)}
                className={cn(
                  "flex w-full cursor-pointer items-start gap-2.5 px-5 py-3 text-left transition-colors hover:bg-surface-2/60",
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                )}
              >
                {it.kind === "blocker" ? (
                  <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger-text" aria-label="Publish blocker" />
                ) : (
                  <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-text" aria-label="Warning" />
                )}
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-[13px] font-medium text-fg">{labelFor(it.pointer)}</span>
                  <span className="text-[12.5px] leading-snug text-fg-2">{it.message}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
