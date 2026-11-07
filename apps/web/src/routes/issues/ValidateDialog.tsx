/**
 * Validate dialog (T042, FR-013, FR-015): a dry run first shows how many simulations will run
 * and what they should cost; the operator picks the mode and, if needed, the keep-rule
 * thresholds within their allowed ranges, then confirms. "Draft and validate" uses the same
 * dialog and drafts the fix in the same request.
 */
import { useQuery } from "@tanstack/react-query";
import { FlaskConical, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import {
  THRESHOLDS,
  draftAndValidate,
  estimateValidation,
  issueKeys,
  validateFix,
  type DetectedIssue,
  type FixKind,
  type ValidationAttempt,
  type ValidationMode,
} from "../../api/issues";
import { useActionKey } from "../../api/paid";
import { Button, Dialog, Field, Figure, Input, Segmented, Skeleton } from "../../components";
import { costUsd, plural } from "../../lib/format";
import { ProblemAlert } from "../../components/ProblemAlert";
import { idempotencyKey } from "../../lib/idempotency";

type Key = keyof typeof THRESHOLDS;
const FIELDS: { key: Key; label: string; unit: string; hint: string }[] = [
  { key: "min_improvement_pp", label: "Improvement needed", unit: "pp", hint: "The headline check must improve by at least this much." },
  { key: "max_regression_pp", label: "Largest drop allowed", unit: "pp", hint: "No other check may drop by more than this." },
  { key: "min_sample", label: "Calls needed", unit: "calls", hint: "Affected calls with a verdict in both batches." },
];

export function thresholdError(key: Key, raw: string): string | null {
  const { min, max } = THRESHOLDS[key];
  const value = Number(raw);
  if (raw.trim() === "" || Number.isNaN(value)) return "Enter a number.";
  if (key === "min_sample" && !Number.isInteger(value)) return "Enter a whole number.";
  if (value < min || value > max) return `Use a value from ${min} to ${max}.`;
  return null;
}

export function ValidateDialog({
  open,
  onOpenChange,
  issue,
  draft,
  onStarted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  issue: DetectedIssue;
  /** Set for "Draft and validate": the kind and guidance of the fix to draft. */
  draft?: { kind?: FixKind; guidance?: string | null } | null;
  onStarted: (attempt: ValidationAttempt) => void;
}) {
  const [mode, setMode] = useState<ValidationMode>("persona");
  const [showThresholds, setShowThresholds] = useState(false);
  const [values, setValues] = useState<Record<Key, string>>(() => ({
    min_improvement_pp: String(THRESHOLDS.min_improvement_pp.default),
    max_regression_pp: String(THRESHOLDS.max_regression_pp.default),
    min_sample: String(THRESHOLDS.min_sample.default),
  }));
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const action = useActionKey();
  const resetKey = action.reset;

  useEffect(() => {
    if (!open) {
      setError(null);
      resetKey();
    }
  }, [open, resetKey]);

  const estimate = useQuery({
    queryKey: issueKeys.estimate(issue.issue_id, mode),
    queryFn: () => estimateValidation(issue.issue_id, mode, idempotencyKey()),
    enabled: open,
    retry: false,
    gcTime: 0,
    staleTime: 0,
  });

  const errors = Object.fromEntries(FIELDS.map((f) => [f.key, thresholdError(f.key, values[f.key])])) as Record<Key, string | null>;
  const invalid = Object.values(errors).some(Boolean);

  async function start() {
    if (invalid) {
      setShowThresholds(true);
      return;
    }
    setPending(true);
    setError(null);
    const settings = {
      mode,
      min_improvement_pp: Number(values.min_improvement_pp),
      max_regression_pp: Number(values.max_regression_pp),
      min_sample: Number(values.min_sample),
    };
    try {
      const attempt = draft
        ? (await draftAndValidate(issue.issue_id, { ...settings, ...draft }, action.current())).validation
        : await validateFix(issue.issue_id, settings, action.current());
      action.reset();
      onStarted(attempt);
      onOpenChange(false);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  }

  const report = estimate.data;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      icon={<FlaskConical aria-hidden />}
      title={draft ? "Draft and validate" : "Validate this fix"}
      description={
        draft
          ? "A fix is drafted, then simulated against the affected calls with and without it. It is kept only if it passes."
          : "The affected calls and a few healthy ones are simulated twice: on the published version and with the fix. The result is stored on the issue."
      }
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" pending={pending} disabled={!report || estimate.isFetching} onClick={() => void start()}>
            {report ? `Run ${plural(report.simulations, "simulation")}` : "Run simulations"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <ProblemAlert error={error} kind="issue" className="[&>div]:mb-0" />
        <Field
          label="Caller in the simulations"
          hint={
            mode === "persona" ? "A simulated caller pursues each original caller's goal." : "The recorded caller turns are replayed word for word."
          }
        >
          {() => (
            <Segmented
              aria-label="Caller in the simulations"
              value={mode}
              onValueChange={setMode}
              options={[
                { value: "persona", label: "Persona" },
                { value: "replay", label: "Replay" },
              ]}
            />
          )}
        </Field>

        <div
          role="group"
          aria-label="Estimate"
          className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-control border border-line px-4 py-3 sm:grid-cols-4"
        >
          {estimate.isError ? (
            <div className="col-span-full">
              <ProblemAlert error={estimate.error} kind="issue" className="[&>div]:mb-0" />
            </div>
          ) : !report ? (
            Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)
          ) : (
            <>
              <Figure label="Affected calls">{report.affected_calls}</Figure>
              <Figure label="Guard calls">{report.guard_calls}</Figure>
              <Figure label="Simulations">{report.simulations}</Figure>
              <Figure label="Estimated cost">{costUsd(report.estimated_cost_usd)}</Figure>
            </>
          )}
        </div>
        {report?.warnings?.map((w) => (
          <p key={w} className="text-[13px] text-fg-2">
            {w}
          </p>
        ))}
        {report?.tools_missing_mock && report.tools_missing_mock.length > 0 && (
          <p className="text-[13px] text-fg-2">
            Tools without a mock response: <span className="font-mono">{report.tools_missing_mock.join(", ")}</span>. They answer with the recorded
            output or a generated stand-in.
          </p>
        )}

        <div className="flex flex-col gap-3">
          <Button
            variant="ghost"
            size="sm"
            className="w-fit"
            icon={<SlidersHorizontal aria-hidden />}
            aria-expanded={showThresholds}
            onClick={() => setShowThresholds((v) => !v)}
          >
            {showThresholds ? "Hide keep rule" : "Change keep rule"}
          </Button>
          {!showThresholds && (
            <p className="text-[13px] text-fg-3">
              Keep the fix if the headline check improves by {values.min_improvement_pp} pp or more, no other check drops by more than{" "}
              {values.max_regression_pp} pp, and at least {values.min_sample} affected calls are judged in both batches.
            </p>
          )}
          {showThresholds && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {FIELDS.map((f) => (
                <Field
                  key={f.key}
                  label={f.label}
                  hint={`${THRESHOLDS[f.key].min} to ${THRESHOLDS[f.key].max} ${f.unit}. ${f.hint}`}
                  error={errors[f.key]}
                >
                  {({ id, describedBy, invalid: bad }) => (
                    <Input
                      id={id}
                      type="number"
                      inputMode="decimal"
                      min={THRESHOLDS[f.key].min}
                      max={THRESHOLDS[f.key].max}
                      step={f.key === "min_sample" ? 1 : 0.5}
                      aria-describedby={describedBy}
                      aria-invalid={bad}
                      value={values[f.key]}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                      suffix={<span className="text-[12px] text-fg-3">{f.unit}</span>}
                    />
                  )}
                </Field>
              ))}
            </div>
          )}
        </div>
      </div>
    </Dialog>
  );
}
