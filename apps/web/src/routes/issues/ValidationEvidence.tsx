/**
 * Validation evidence (T043, FR-016): the keep rule's thresholds, the headline check on the
 * affected calls, every check by call set with blocking and not-enough-data markers, the reasons
 * in plain language, links to the control and treatment batches, and every earlier attempt.
 */
import { CircleStop, FlaskConical, History, Scale } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { EvaluatorEvidence, ValidationAttempt } from "../../api/issues";
import { Badge, Button, cn, type Column, deltaTone, Figure, Panel, Table } from "../../components";
import { AttemptBadge, SET_LABELS, reasonText } from "./shared";
import { costUsd, pct, pp, timeAgo } from "../../lib/format";

const SET_ORDER: Record<EvaluatorEvidence["set"], number> = { affected: 0, guard: 1, combined: 2 };

function Note({ row }: { row: EvaluatorEvidence }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {row.blocking && <Badge tone="danger">Blocks the fix</Badge>}
      {row.insufficient_data && <Badge tone="neutral">Not enough calls</Badge>}
      {(row.version_mismatch ?? 0) > 0 && (
        <span
          className="whitespace-nowrap text-[12px] text-fg-3"
          title="Calls judged by different versions of the check in the two batches are left out."
        >
          {row.version_mismatch} left out
        </span>
      )}
    </span>
  );
}

const COLUMNS: Column<EvaluatorEvidence>[] = [
  {
    key: "check",
    header: "Check",
    cell: (r) => (
      <span className="flex min-w-0 flex-col gap-0.5 py-0.5">
        <span className="text-[13px] font-medium text-fg">{r.evaluator_name}</span>
        <span className="text-[12px] text-fg-3">{SET_LABELS[r.set]}</span>
      </span>
    ),
  },
  { key: "n", header: "Pairs", numeric: true, hideOnNarrow: true, cell: (r) => r.n },
  { key: "control", header: "Without fix", numeric: true, hideOnNarrow: true, cell: (r) => pct(r.control_rate) },
  { key: "treatment", header: "With fix", numeric: true, hideOnNarrow: true, cell: (r) => pct(r.treatment_rate) },
  { key: "delta", header: "Change", numeric: true, cell: (r) => <span className={cn("font-medium", deltaTone(r.delta_pp))}>{pp(r.delta_pp)}</span> },
  { key: "note", header: <span className="sr-only">Notes</span>, cell: (r) => <Note row={r} /> },
];

function Attempt({ a }: { a: ValidationAttempt }) {
  const names = Object.fromEntries((a.evaluator_results ?? []).map((r) => [r.evaluator_id, r.evaluator_name]));
  const t = a.thresholds;
  const rows = [...(a.evaluator_results ?? [])].sort(
    (x, y) => SET_ORDER[x.set] - SET_ORDER[y.set] || x.evaluator_name.localeCompare(y.evaluator_name),
  );
  const reasons = a.reasons ?? [];
  const h = a.headline;
  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-3 text-[13px] text-fg-3">
        <span>
          Keep if the headline improves by {t.min_improvement_pp} pp or more, nothing drops by more than {t.max_regression_pp} pp, with at least{" "}
          {t.min_sample} calls.
        </span>
        <span className="ml-auto flex flex-wrap gap-3">
          <Link className="rounded-inline font-medium text-accent-text hover:underline" to={`/simulations/${a.control_experiment_id}`}>
            Control batch
          </Link>
          <Link className="rounded-inline font-medium text-accent-text hover:underline" to={`/simulations/${a.treatment_experiment_id}`}>
            Batch with the fix
          </Link>
        </span>
      </div>
      {a.status === "running" ? (
        <p className="flex items-center gap-2 px-5 py-6 text-[14px] text-fg-2">
          <FlaskConical className="size-4 text-accent-text" aria-hidden />
          Simulating {a.affected_call_ids.length} affected and {a.guard_call_ids.length} guard calls in both batches. The result appears here when
          they finish.
        </p>
      ) : a.status === "cancelled" ? (
        <p className="px-5 py-6 text-[14px] text-fg-2">This validation was cancelled before it finished. Nothing was decided.</p>
      ) : (
        <>
          {h && (
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-line px-5 py-4 sm:grid-cols-4">
              <Figure label={`${h.evaluator_name} without fix`}>{pct(h.control_rate)}</Figure>
              <Figure label="With fix">{pct(h.treatment_rate)}</Figure>
              <Figure label="Change">
                <span className={deltaTone(h.delta_pp)}>{pp(h.delta_pp)}</span>
              </Figure>
              <Figure label="Affected calls judged">{h.n}</Figure>
            </div>
          )}
          {reasons.length > 0 && (
            <ul className="flex flex-col gap-1.5 border-b border-line px-5 py-3 text-[13px] text-fg">
              {reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span
                    className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", r.code === "insufficient_data" ? "bg-fg-3" : "bg-danger")}
                    aria-hidden
                  />
                  {reasonText(r, names, t)}
                </li>
              ))}
            </ul>
          )}
          {rows.length > 0 && <Table caption="Checks by call set" columns={COLUMNS} rows={rows} rowKey={(r) => `${r.evaluator_id}-${r.set}`} />}
          <p className="px-5 py-3 text-[12px] text-fg-3">
            {a.treatment_runs_failed ?? 0} of {a.treatment_runs_total ?? 0} simulations with the fix failed to run. Cost{" "}
            {costUsd(a.cost_usd ?? a.estimated_cost_usd)}.{a.finished_at && ` Finished ${timeAgo(a.finished_at)}.`}
          </p>
        </>
      )}
    </div>
  );
}

export function ValidationEvidence({
  attempts,
  canCancel,
  cancelling,
  onCancel,
}: {
  attempts: ValidationAttempt[];
  canCancel: boolean;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const latest = attempts[0];
  if (!latest) return null;
  const shown = attempts.find((a) => a.attempt === selected) ?? latest;
  return (
    <Panel
      title={`Validation ${shown.attempt} of revision ${shown.fix_revision}`}
      description={`${shown.mode === "replay" ? "Replay" : "Persona"} simulations, started ${timeAgo(shown.started_at)}${shown.auto ? " by draft and validate" : ""}.`}
      icon={<Scale aria-hidden />}
      bodyClassName="p-0"
      actions={
        <span className="flex items-center gap-2">
          <AttemptBadge attempt={shown} />
          {canCancel && shown.status === "running" && (
            <Button size="sm" variant="secondary" icon={<CircleStop aria-hidden />} pending={cancelling} onClick={onCancel}>
              Cancel
            </Button>
          )}
        </span>
      }
    >
      <Attempt a={shown} />
      {attempts.length > 1 && (
        <div className="border-t border-line px-5 py-3">
          <p className="mb-2 flex items-center gap-1.5 text-[13px] text-fg-3">
            <History className="size-3.5" aria-hidden />
            Earlier attempts
          </p>
          <ul className="flex flex-wrap gap-2" aria-label="Validation attempts">
            {attempts.map((a) => (
              <li key={a.attempt}>
                <button
                  type="button"
                  aria-pressed={a.attempt === shown.attempt}
                  onClick={() => setSelected(a.attempt)}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-control border px-2.5 py-1.5 text-[13px] transition-colors",
                    a.attempt === shown.attempt
                      ? "border-accent bg-accent-soft/50 text-fg"
                      : "border-line bg-surface text-fg-2 hover:border-line-strong",
                  )}
                >
                  Attempt {a.attempt}
                  <span className="text-fg-3">rev {a.fix_revision}</span>
                  <AttemptBadge attempt={a} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
