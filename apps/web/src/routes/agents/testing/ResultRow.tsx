/**
 * One test result (US1, T042, FR-008, FR-009): the effective verdict, and on expand the caller
 * turn, the expected behaviour, the agent reply, tool calls with what answered them, the flow nodes
 * visited, the judge's verdict and reasoning, and the manual override. An override keeps the
 * judge's verdict visible and is labelled "Manual".
 */
import { ArrowRight, ChevronDown, Gavel, UserCheck, Wrench } from "lucide-react";
import { useId, useState } from "react";
import type { TestCategory, TestResult } from "../../../api/testing";
import { Badge, Button, cn, focusRing } from "../../../components";
import { AnswerSourceBadge } from "../../simulations/shared";
import { CategoryLabel, TestStatusBadge } from "./categories";

function Block({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-[12px] text-fg-3">{label}</span>
      <div className="min-w-0 whitespace-pre-wrap break-words text-[13px] leading-relaxed text-fg">{children}</div>
    </div>
  );
}

const JUDGE_LABEL = { passed: "passed", failed: "failed", error: "could not judge" } as const;

export function ResultRow({
  result,
  categories,
  canOverride,
  pending,
  onOverride,
  defaultOpen = false,
}: {
  result: TestResult;
  categories: TestCategory[] | undefined;
  canOverride: boolean;
  pending: boolean;
  onOverride: (status: "passed" | "failed" | null) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const settled = result.status !== null && result.status !== undefined;
  return (
    <li className="flex flex-col">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "grid w-full cursor-pointer grid-cols-[88px_minmax(0,1fr)_auto] items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-accent-soft/35",
          focusRing,
        )}
      >
        <span className="flex flex-col items-start gap-1">
          {settled ? <TestStatusBadge status={result.status} /> : <Badge tone="neutral">Waiting</Badge>}
          {result.is_manual && (
            <Badge tone="accent" icon={<UserCheck aria-hidden />}>
              Manual
            </Badge>
          )}
        </span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex min-w-0 items-center gap-3">
            <span className="truncate text-[14px] font-medium text-fg">{result.case_name}</span>
            <CategoryLabel slug={result.category} categories={categories} className="hidden shrink-0 sm:inline-flex" />
          </span>
          <span className="truncate text-[13px] text-fg-3">{result.agent_response ?? result.error_message ?? result.user_prompt}</span>
        </span>
        <span className="flex items-center gap-3">
          {result.duration_ms != null && (
            <span className="hidden font-mono text-[12px] text-fg-3 tnum sm:inline">{(result.duration_ms / 1000).toFixed(1)} s</span>
          )}
          <ChevronDown className={cn("size-4 text-fg-3 transition-transform", open && "rotate-180")} aria-hidden />
        </span>
      </button>
      {open && (
        <div id={bodyId} className="flex flex-col gap-4 border-t border-line bg-surface-2/50 px-5 py-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Block label="Caller says">{result.user_prompt}</Block>
            <Block label="Expected behaviour">{result.expected_behaviour}</Block>
          </div>
          <Block label="Agent reply">
            {result.agent_response ?? <span className="text-fg-3">{result.error_message ?? (settled ? "No reply" : "Waiting for the reply")}</span>}
          </Block>
          {(result.tool_calls?.length ?? 0) > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] text-fg-3">Tool calls</span>
              <ul className="flex flex-col gap-1.5">
                {result.tool_calls!.map((t, i) => (
                  <li key={i} className="flex min-w-0 flex-col gap-1 rounded-control border border-line bg-surface px-3 py-2">
                    <span className="flex flex-wrap items-center gap-2">
                      <Wrench className="size-3.5 text-fg-3" aria-hidden />
                      <span className="font-mono text-[13px] text-fg">{t.name}</span>
                      {t.answer_source && <AnswerSourceBadge source={t.answer_source} />}
                    </span>
                    <span className="break-all font-mono text-[12px] text-fg-3">{JSON.stringify(t.arguments)}</span>
                    {t.output && <span className="break-all font-mono text-[12px] text-fg-2">{t.output}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(result.nodes_visited?.length ?? 0) > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] text-fg-3">Nodes visited</span>
              <ol className="flex flex-wrap items-center gap-1.5" aria-label="Nodes visited">
                {result.nodes_visited!.map((n, i) => (
                  <li key={`${n}-${i}`} className="flex items-center gap-1.5">
                    {i > 0 && <ArrowRight className="size-3 text-fg-3" aria-hidden />}
                    <Badge tone="neutral">{n}</Badge>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {settled && (
            <div className="flex flex-col gap-1.5 rounded-control border border-line bg-surface px-3.5 py-3">
              <span className="flex flex-wrap items-center gap-2 text-[13px] text-fg-2">
                <Gavel className="size-3.5 text-fg-3" aria-hidden />
                Judge {result.judge_status ? JUDGE_LABEL[result.judge_status] : "pending"}
                {result.is_manual && result.judge_status && (
                  <span className="text-fg-3">
                    (overridden to {result.override_status}
                    {result.override_note ? `: ${result.override_note}` : ""})
                  </span>
                )}
              </span>
              {result.judge_reasoning && <p className="text-[13px] leading-relaxed text-fg">{result.judge_reasoning}</p>}
              {result.error_message && <p className="text-[13px] text-warning-text">{result.error_message}</p>}
            </div>
          )}
          {settled && (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Verdict for ${result.case_name}`}>
              <span className="mr-1 text-[13px] text-fg-3">{canOverride ? "Override the verdict" : "You can override once the run finishes"}</span>
              <Button
                size="sm"
                variant={result.override_status === "passed" ? "primary" : "secondary"}
                disabled={!canOverride || pending || result.override_status === "passed"}
                onClick={() => onOverride("passed")}
              >
                Mark passed
              </Button>
              <Button
                size="sm"
                variant={result.override_status === "failed" ? "primary" : "secondary"}
                disabled={!canOverride || pending || result.override_status === "failed"}
                onClick={() => onOverride("failed")}
              >
                Mark failed
              </Button>
              {result.is_manual && (
                <Button size="sm" variant="ghost" disabled={!canOverride || pending} onClick={() => onOverride(null)}>
                  Use the judge's verdict
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}
