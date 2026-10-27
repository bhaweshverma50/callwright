import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, MessageCircleQuestion, ShieldPlus, TextSearch } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { useCalls } from "../../api/calls";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import {
  createCustomEvaluator,
  newIdempotencyKey,
  qualityKeys,
  trialCustomEvaluator,
  updateCustomEvaluator,
  useJudgeModels,
  type CustomConfig,
  type CustomType,
  type Evaluator,
  type JudgeQuestionConfig,
  type PhraseCheckConfig,
  type TrialResult,
} from "../../api/quality";
import { Badge, Button, Dialog, Field, Input, Segmented, Select, SwitchControl, Textarea, toast } from "../../components";
import { when } from "../calls/format";
import { NAME_RULE, toVariableName } from "../agents/quality/variableName";
import { CustomCheckTemplatePicker } from "./CustomCheckTemplatePicker";
import { VERDICT_LABELS, VERDICT_TONES } from "./evaluatorMeta";

type Phrase = Required<Pick<PhraseCheckConfig, "pattern" | "mode" | "target" | "is_regex" | "case_sensitive">>;
type Judge = { question: string; pass_when: "yes" | "no"; judge_model: string };

const PHRASE_DEFAULT: Phrase = { pattern: "", mode: "forbidden", target: "agent", is_regex: false, case_sensitive: false };

/**
 * "Add custom check" (US5, T062, T088): a template choice, then that template's form with Back.
 * The machine name is derived from the display name; Create is enabled once the name and the
 * phrase (or question) are filled. Editing skips the template step; a definition change makes a
 * new version.
 */
export function CustomEvaluatorDialog({
  open,
  onOpenChange,
  existing,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing?: Evaluator | null;
  onSaved?: (e: Evaluator) => void;
}) {
  const [type, setType] = useState<CustomType | null>(null);
  const editing = existing ?? null;
  const step: CustomType | null = editing ? (editing.evaluator_type as CustomType) : type;
  const close = (o: boolean) => {
    onOpenChange(o);
    if (!o) window.setTimeout(() => setType(null), 200);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={close}
      size="lg"
      icon={step === "phrase_check" ? <TextSearch aria-hidden /> : step === "llm_judge_custom" ? <MessageCircleQuestion aria-hidden /> : <ShieldPlus aria-hidden />}
      title={editing ? `Edit ${editing.display_name}` : step === null ? "Add custom check" : step === "phrase_check" ? "Required or forbidden phrase" : "Custom judge question"}
      description={
        editing
          ? `Changing the definition creates version ${editing.current_version + 1}. Results already produced keep version ${editing.current_version}.`
          : step === null
            ? "Start from a template. Saved checks appear in every agent's quality tab, off until you turn them on."
            : "Try it on a call before you create it."
      }
    >
      {open && (
        <AnimatePresence mode="wait" initial={false}>
          {step === null ? (
            <motion.div key="pick" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.18 }}>
              <CustomCheckTemplatePicker onPick={setType} />
            </motion.div>
          ) : (
            <motion.div key={step} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }} transition={{ duration: 0.18 }}>
              <CheckForm
                type={step}
                existing={editing}
                onBack={editing ? undefined : () => setType(null)}
                onCancel={() => close(false)}
                onSaved={(e) => {
                  onSaved?.(e);
                  close(false);
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </Dialog>
  );
}

function TrialPanel({ type, config, ready }: { type: CustomType; config: CustomConfig; ready: boolean }) {
  const calls = useCalls(useMemo(() => new URLSearchParams({ page_size: "20", status: "completed" }), []));
  const [callId, setCallId] = useState<string | undefined>(undefined);
  const [result, setResult] = useState<TrialResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const options = (calls.data?.items ?? []).map((c) => ({ value: c.call_id, label: `${c.agent.name}, ${when(c.started_at)}`, meta: c.call_id.slice(-6) }));
  const chosen = callId ?? options[0]?.value;
  const run = async () => {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await trialCustomEvaluator({ evaluator_type: type, config, call_id: chosen }, newIdempotencyKey()));
    } catch (e) {
      setResult(null);
      setError(isApiError(e) && e.status === 422 ? (e.problem.errors?.[0]?.message ?? e.problem.detail ?? "Check the fields above.") : problemMessage(e, "call"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-label="Try it" className="flex flex-col gap-3 rounded-panel border border-dashed border-line-strong bg-surface-2/40 p-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
          <span id="trial-call" className="text-[13px] font-medium text-fg">
            Try it on a call
          </span>
          <Select
            aria-label="Call to try on"
            value={chosen}
            onValueChange={setCallId}
            options={options}
            placeholder={calls.isPending ? "Loading calls" : "No finished calls yet"}
            disabled={!options.length}
          />
        </div>
        <Button icon={<FlaskConical aria-hidden />} onClick={() => void run()} disabled={!ready || !chosen} pending={busy}>
          Try on call
        </Button>
      </div>
      {type === "llm_judge_custom" && <p className="text-[12px] text-fg-3">A judge trial is charged like one judged call.</p>}
      {error && (
        <p role="alert" className="text-[12.5px] text-danger-text">
          {error}
        </p>
      )}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex flex-col gap-1.5 rounded-control border border-line bg-surface p-3"
            data-testid="trial-result"
          >
            <span className="flex items-center gap-2">
              <Badge tone={VERDICT_TONES[result.verdict]}>{VERDICT_LABELS[result.verdict]}</Badge>
              {result.score != null && <span className="font-mono text-[12px] text-fg-3 tnum">score {result.score}</span>}
              {result.charged_usd ? <span className="ml-auto font-mono text-[11.5px] text-fg-3">charged ${result.charged_usd.toFixed(4)}</span> : null}
            </span>
            <p className="text-[13px] leading-relaxed text-fg">{result.rationale}</p>
            {result.evidence?.quote && <blockquote className="rounded-inline bg-surface-2 px-2.5 py-1.5 text-[12.5px] italic text-fg-2">{result.evidence.quote}</blockquote>}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function CheckForm({
  type,
  existing,
  onBack,
  onCancel,
  onSaved,
}: {
  type: CustomType;
  existing: Evaluator | null;
  onBack?: () => void;
  onCancel: () => void;
  onSaved: (e: Evaluator) => void;
}) {
  const qc = useQueryClient();
  const models = useJudgeModels();
  const defaultModel = models.data?.find((m) => m.is_default)?.model_id ?? models.data?.[0]?.model_id ?? "";
  const [displayName, setDisplayName] = useState(existing?.display_name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [phrase, setPhrase] = useState<Phrase>({ ...PHRASE_DEFAULT, ...((existing?.config as PhraseCheckConfig | undefined) ?? {}) });
  const initialJudge = existing?.config as JudgeQuestionConfig | undefined;
  const [judge, setJudge] = useState<Judge>({ question: initialJudge?.question ?? "", pass_when: initialJudge?.pass_when ?? "yes", judge_model: initialJudge?.judge_model ?? "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const machine = existing ? existing.name : toVariableName(displayName);
  const judgeModel = judge.judge_model || defaultModel;
  const config: CustomConfig = type === "phrase_check" ? phrase : { question: judge.question.trim(), pass_when: judge.pass_when, ...(judgeModel && { judge_model: judgeModel }) };
  const filled = type === "phrase_check" ? phrase.pattern.trim().length > 0 : judge.question.trim().length > 0;
  const ready = Boolean(displayName.trim() && machine && filled);

  const save = async () => {
    setSaving(true);
    setErrors({});
    try {
      const saved = existing
        ? await updateCustomEvaluator(existing.id, { display_name: displayName.trim(), description: description.trim() || null, config })
        : await createCustomEvaluator({ display_name: displayName.trim(), description: description.trim() || null, evaluator_type: type, config });
      await qc.invalidateQueries({ queryKey: qualityKeys.all });
      toast({
        tone: "success",
        title: existing ? `Saved ${saved.display_name}` : `Created ${saved.display_name}`,
        description: existing ? `Now on version ${saved.current_version}.` : "Turn it on in any agent's quality tab.",
      });
      onSaved(saved);
    } catch (e) {
      if (isApiError(e) && e.status === 409) setErrors({ display_name: e.problem.detail ?? `You already have a custom check named ${machine}` });
      else if (isApiError(e) && e.status === 422) {
        const out: Record<string, string> = {};
        for (const fe of e.problem.errors ?? []) out[fe.pointer.split("/").pop() ?? ""] ??= fe.message;
        if (!Object.keys(out).length) out.pattern = e.problem.detail ?? "Check the fields.";
        setErrors(out);
      } else toast({ tone: "error", title: "Could not save the check", description: problemMessage(e, "check") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="flex flex-col gap-5 pb-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) void save();
      }}
    >
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
        <Field
          label="Name"
          error={errors.display_name ?? errors.name ?? (displayName.trim() && !machine ? NAME_RULE : null)}
          hint={
            machine ? (
              <span className="inline-flex flex-wrap items-center gap-1.5">
                {existing ? "Machine name" : "Saved as"}
                <code data-testid="machine-name" className="rounded-inline bg-accent-soft px-1.5 py-0.5 font-mono text-[12px] text-accent-text">
                  {machine}
                </code>
              </span>
            ) : (
              "Shown in the catalog and on every result."
            )
          }
        >
          {(ids) => (
            <Input
              id={ids.id}
              aria-describedby={ids.describedBy}
              aria-invalid={ids.invalid}
              autoFocus
              maxLength={80}
              value={displayName}
              placeholder={type === "phrase_check" ? "No guarantees" : "Confirms date of birth"}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          )}
        </Field>
        <Field label="Description" hint="Optional. What the check is for.">
          {(ids) => <Input id={ids.id} aria-describedby={ids.describedBy} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
      </div>

      {type === "phrase_check" ? (
        <div className="flex flex-col gap-4">
          <Field label="Phrase or pattern" error={errors.pattern ?? null} hint={phrase.is_regex ? "Linear-time patterns only: no backreferences or lookarounds." : "Matched as plain text."}>
            {(ids) => (
              <Input
                id={ids.id}
                aria-describedby={ids.describedBy}
                aria-invalid={ids.invalid}
                maxLength={500}
                className="font-mono"
                value={phrase.pattern}
                placeholder={phrase.is_regex ? "guarantee(d)?" : "guaranteed approval"}
                onChange={(e) => setPhrase({ ...phrase, pattern: e.target.value })}
              />
            )}
          </Field>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg">Rule</span>
              <Segmented
                aria-label="Rule"
                fill
                size="sm"
                value={phrase.mode}
                onValueChange={(mode) => setPhrase({ ...phrase, mode })}
                options={[
                  { value: "forbidden", label: "Forbidden" },
                  { value: "required", label: "Required" },
                ]}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg">Applies to</span>
              <Segmented
                aria-label="Applies to"
                fill
                size="sm"
                value={phrase.target}
                onValueChange={(target) => setPhrase({ ...phrase, target })}
                options={[
                  { value: "agent", label: "Agent" },
                  { value: "user", label: "Caller" },
                  { value: "both", label: "Both" },
                ]}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg">Match as</span>
              <Segmented
                aria-label="Match as"
                fill
                size="sm"
                value={phrase.is_regex ? "pattern" : "text"}
                onValueChange={(v) => setPhrase({ ...phrase, is_regex: v === "pattern" })}
                options={[
                  { value: "text", label: "Plain text" },
                  { value: "pattern", label: "Pattern" },
                ]}
              />
            </div>
          </div>
          <label className="flex items-center justify-between gap-4 rounded-control border border-line px-3.5 py-2.5">
            <span className="flex flex-col">
              <span className="text-[13px] font-medium text-fg">Case sensitive</span>
              <span className="text-[12.5px] text-fg-3">Off matches "Guaranteed" and "guaranteed" alike.</span>
            </span>
            <SwitchControl aria-label="Case sensitive" checked={phrase.case_sensitive} onCheckedChange={(case_sensitive) => setPhrase({ ...phrase, case_sensitive })} />
          </label>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Field
            label="Yes or no question"
            error={errors.question ?? null}
            aside={<span className="font-mono text-[11.5px] text-fg-3 tnum">{judge.question.length}/1000</span>}
            hint="The judge reads the transcript as data; instructions spoken in the call cannot change the answer."
          >
            {(ids) => (
              <Textarea
                id={ids.id}
                aria-describedby={ids.describedBy}
                aria-invalid={ids.invalid}
                maxLength={1000}
                className="min-h-20"
                value={judge.question}
                placeholder="Did the agent confirm the caller's date of birth?"
                onChange={(e) => setJudge({ ...judge, question: e.target.value })}
              />
            )}
          </Field>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg">Passes when the answer is</span>
              <Segmented
                aria-label="Passes when the answer is"
                fill
                value={judge.pass_when}
                onValueChange={(pass_when) => setJudge({ ...judge, pass_when })}
                options={[
                  { value: "yes", label: "Yes" },
                  { value: "no", label: "No" },
                ]}
              />
            </div>
            <Field label="Judge model" error={errors.judge_model ?? null} hint="Charged per judged call.">
              {(ids) => (
                <Select
                  id={ids.id}
                  describedBy={ids.describedBy}
                  value={judgeModel || undefined}
                  onValueChange={(judge_model) => setJudge({ ...judge, judge_model })}
                  options={(models.data ?? []).map((m) => ({ value: m.model_id, label: m.display_name, meta: m.is_default ? "default" : undefined }))}
                  placeholder="Loading models"
                />
              )}
            </Field>
          </div>
        </div>
      )}

      <TrialPanel type={type} config={config} ready={filled} />

      <div className="-mx-5 mt-1 flex items-center gap-2 border-t border-line px-5 pt-3.5">
        {onBack && (
          <Button type="button" variant="ghost" icon={<ArrowLeft aria-hidden />} onClick={onBack}>
            Back
          </Button>
        )}
        <span className="ml-auto" />
        <Button type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!ready} pending={saving}>
          {existing ? "Save changes" : "Create check"}
        </Button>
      </div>
    </form>
  );
}
