import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, CircleDollarSign, Minus, Pencil, Plus, RotateCcw, Star, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useId, useMemo, useState } from "react";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import {
  putEvalSetting,
  qualityKeys,
  settingErrors,
  type AgentEvalSetting,
  type EvalSettingBody,
  type JudgeModel,
  type SettingsField,
} from "../../../api/quality";
import { Badge, Button, IconButton, Input, Select, SwitchControl, Textarea, Tooltip, cn, focusRing, toast } from "../../../components";
import { COST_LABELS, SCOPE_LABELS, evaluatorIcon } from "../../evaluators/evaluatorMeta";
import { displayValue, fieldError, fmtNumber, helperText, optionsFor, parseFieldValue, schemaFields } from "./settingsSchema";

export const HEADLINE_LIMIT = 4;
export const HEADLINE_LIMIT_MESSAGE = "Up to 4 headline checks per agent";

type FormValues = Record<string, unknown>;

const valuesOf = (s: AgentEvalSetting): FormValues => ({ ...s.effective_settings });
const textOf = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const same = (a: FormValues, b: FormValues) => Object.keys({ ...a, ...b }).every((k) => textOf(a[k]) === textOf(b[k]));

/** Whole-number stepper (FR-038): typing is allowed, the buttons stay inside the range. */
function NumberStepper({
  id,
  field,
  value,
  invalid,
  describedBy,
  onChange,
}: {
  id: string;
  field: SettingsField;
  value: unknown;
  invalid: boolean;
  describedBy?: string;
  onChange: (v: unknown) => void;
}) {
  const step = field.step ?? 1;
  const n = typeof value === "number" ? value : Number(value);
  const bump = (by: number) => {
    const base = Number.isFinite(n) ? n : Number(field.default ?? 0);
    let next = Math.round((base + by) * 1e6) / 1e6;
    if (field.min !== undefined) next = Math.max(field.min, next);
    if (field.max !== undefined) next = Math.min(field.max, next);
    onChange(next);
  };
  return (
    <div className="flex items-stretch">
      <button
        type="button"
        aria-label={`Decrease ${field.label}`}
        disabled={Number.isFinite(n) && field.min !== undefined && n <= field.min}
        onClick={() => bump(-step)}
        className={cn(
          "grid w-9 shrink-0 cursor-pointer place-items-center rounded-l-control border border-r-0 border-line-strong bg-surface-2 text-fg-2 hover:text-fg disabled:cursor-not-allowed disabled:text-fg-3",
          focusRing,
        )}
      >
        <Minus className="size-3.5" aria-hidden />
      </button>
      <Input
        id={id}
        role="spinbutton"
        inputMode={field.type === "int" ? "numeric" : "decimal"}
        aria-valuemin={field.min}
        aria-valuemax={field.max}
        aria-valuenow={Number.isFinite(n) ? n : undefined}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        value={textOf(value)}
        onChange={(e) => onChange(parseFieldValue(field, e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            e.preventDefault();
            bump(e.key === "ArrowUp" ? step : -step);
          }
        }}
        className="w-28 rounded-none text-center font-mono tnum"
      />
      <button
        type="button"
        aria-label={`Increase ${field.label}`}
        disabled={Number.isFinite(n) && field.max !== undefined && n >= field.max}
        onClick={() => bump(step)}
        className={cn(
          "grid w-9 shrink-0 cursor-pointer place-items-center rounded-r-control border border-l-0 border-line-strong bg-surface-2 text-fg-2 hover:text-fg disabled:cursor-not-allowed disabled:text-fg-3",
          focusRing,
        )}
      >
        <Plus className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

function SettingField({
  field,
  value,
  error,
  models,
  adjusted,
  onChange,
}: {
  field: SettingsField;
  value: unknown;
  error: string | null;
  models: JudgeModel[] | undefined;
  adjusted: boolean;
  onChange: (v: unknown) => void;
}) {
  const id = useId();
  const helpId = `${id}-help`;
  const helper = helperText(field, models);
  const range =
    (field.type === "int" || field.type === "number") && field.min !== undefined && field.max !== undefined
      ? `${fmtNumber(field.min)} to ${fmtNumber(field.max)}`
      : null;
  let control;
  if (field.type === "int" || field.type === "number") {
    control = <NumberStepper id={id} field={field} value={value} invalid={Boolean(error)} describedBy={helpId} onChange={onChange} />;
  } else if (field.type === "select") {
    const opts = optionsFor(field, models).map((o) => ({
      value: o,
      label: displayValue(field, o, models),
      meta: field.options_source === "judge_models" ? o : undefined,
    }));
    control = (
      <Select
        id={id}
        value={textOf(value)}
        onValueChange={onChange}
        options={opts}
        invalid={Boolean(error)}
        describedBy={helpId}
        className="w-full sm:w-64"
      />
    );
  } else if (field.type === "bool") {
    control = <SwitchControl id={id} checked={value === true} onCheckedChange={onChange} describedBy={helpId} />;
  } else if (field.type === "text_long") {
    control = <Textarea id={id} value={textOf(value)} aria-describedby={helpId} onChange={(e) => onChange(e.target.value)} />;
  } else {
    control = <Input id={id} value={textOf(value)} aria-describedby={helpId} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <div className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="flex min-w-0 flex-col gap-0.5">
        <label htmlFor={id} className="text-[13px] font-medium text-fg">
          {field.label}
        </label>
        {range && <span className="font-mono text-[12px] text-fg-3 tnum">{range}</span>}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5 sm:items-end">
        {control}
        {error ? (
          <p id={helpId} role="alert" className="text-[13px] text-danger-text sm:text-right">
            {error}
          </p>
        ) : (
          <p id={helpId} className="max-w-[56ch] text-[13px] leading-relaxed text-fg-3 sm:text-right">
            {adjusted && <span className="font-medium text-warning-text">Adjusted to fit this version's range. </span>}
            {helper}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * One check on the agent's quality tab (US2, T085, FR-038, FR-039). The on/off switch and the
 * headline star save at once with the saved field values; field edits stay pending on this card
 * with Discard and Save settings. Every save is the whole setting.
 */
export function EvaluatorCard({
  agentId,
  setting,
  models,
  headlineCount,
  evaluatorType,
  onEditCustom,
  onDeleteCustom,
}: {
  agentId: string;
  /** Custom checks: phrase_check or llm_judge_custom, for the icon. */
  evaluatorType?: string;
  setting: AgentEvalSetting;
  models: JudgeModel[] | undefined;
  headlineCount: number;
  onEditCustom?: () => void;
  onDeleteCustom?: () => void;
}) {
  const qc = useQueryClient();
  const fields = useMemo(() => schemaFields(setting.settings_schema), [setting.settings_schema]);
  const saved = useMemo(() => valuesOf(setting), [setting]);
  const [draft, setDraft] = useState<FormValues>(saved);
  const [lastSaved, setLastSaved] = useState(saved);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<null | "toggle" | "save" | "headline">(null);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [cardError, setCardError] = useState<string | null>(null);
  if (lastSaved !== saved) {
    // A save elsewhere (switch, another tab after refetch): keep pending edits, rebase the rest.
    setLastSaved(saved);
    setDraft((d) => (same(d, lastSaved) ? saved : d));
  }
  const errors = Object.fromEntries(fields.map((f) => [f.key, fieldError(f, draft[f.key], models)]));
  const invalid = Object.values(errors).some(Boolean);
  const dirty = !same(draft, saved);
  const Icon = evaluatorIcon(setting.kind === "custom" ? (evaluatorType ?? setting.name) : setting.name);
  const headlineFull = !setting.is_headline && headlineCount >= HEADLINE_LIMIT;

  const put = async (body: EvalSettingBody, kind: "toggle" | "save" | "headline") => {
    setBusy(kind);
    setCardError(null);
    try {
      const next = await putEvalSetting(agentId, setting.evaluator_id, body);
      qc.setQueryData<AgentEvalSetting[]>(qualityKeys.settings(agentId), (list) =>
        list?.map((s) => (s.evaluator_id === next.evaluator_id ? next : s)),
      );
      if (kind === "save") setServerErrors({});
      return true;
    } catch (e) {
      if (isApiError(e) && e.status === 422 && kind === "save") {
        setServerErrors(settingErrors(e));
        setOpen(true);
      } else if (isApiError(e) && e.status === 409) {
        setCardError(e.problem.detail ?? HEADLINE_LIMIT_MESSAGE);
      } else {
        toast({ tone: "error", title: `Could not save ${setting.display_name}`, description: problemMessage(e, "check") });
      }
      return false;
    } finally {
      setBusy(null);
    }
  };

  const savedOverrides = setting.overrides ?? {};
  const toggle = (enabled: boolean) => void put({ enabled, overrides: savedOverrides, is_headline: setting.is_headline }, "toggle");
  const headline = () => void put({ enabled: setting.enabled, overrides: savedOverrides, is_headline: !setting.is_headline }, "headline");
  const save = () => void put({ enabled: setting.enabled, overrides: { ...draft }, is_headline: setting.is_headline }, "save");

  const panelId = useId();
  const judge = setting.cost_class === "llm_judge";
  return (
    <motion.li
      layout="position"
      className={cn(
        "relative overflow-hidden rounded-control border bg-surface transition-[border-color,box-shadow] duration-200",
        setting.enabled ? "border-line-strong shadow-1" : "border-line",
        dirty && "border-accent/60 shadow-[0_0_0_3px_var(--accent-soft)]",
      )}
      data-testid={`check-${setting.name}`}
    >
      {setting.enabled && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-[radial-gradient(120%_100%_at_0%_0%,var(--glow-a),transparent_70%)]"
        />
      )}
      <div className="relative flex items-start gap-3 px-4 py-3.5">
        <span
          className={cn(
            "grid size-9 shrink-0 place-items-center rounded-control transition-colors duration-300 [&_svg]:size-[18px]",
            setting.enabled ? "bg-accent text-white" : "bg-surface-3 text-fg-3",
          )}
        >
          <Icon aria-hidden />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="text-[14px] font-semibold text-fg">{setting.display_name}</h3>
            <Badge>{SCOPE_LABELS[setting.scope]}</Badge>
            {judge ? (
              <Badge tone="warning" icon={<CircleDollarSign aria-hidden />}>
                {COST_LABELS.llm_judge}
              </Badge>
            ) : (
              <Badge tone="success">{COST_LABELS.free}</Badge>
            )}
            {setting.kind === "custom" && <Badge tone="accent">Custom</Badge>}
            <span className="font-mono text-[12px] text-fg-3">v{setting.current_version}</span>
          </div>
          {setting.description && <p className="text-[13px] leading-relaxed text-fg-2">{setting.description}</p>}
          {judge && (
            <p className="text-[12px] text-warning-text">
              Costs credit per call
              {setting.est_cost_per_call_usd != null ? `, about $${setting.est_cost_per_call_usd.toFixed(4)} each` : ""}.
            </p>
          )}
          {cardError && (
            <p role="alert" className="text-[13px] text-danger-text">
              {cardError}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {setting.kind === "custom" && (
            <>
              <IconButton label={`Edit ${setting.display_name}`} onClick={onEditCustom} className="size-8">
                <Pencil className="size-4" aria-hidden />
              </IconButton>
              <IconButton label={`Delete ${setting.display_name}`} onClick={onDeleteCustom} className="size-8">
                <Trash2 className="size-4" aria-hidden />
              </IconButton>
            </>
          )}
          <Tooltip
            content={setting.is_headline ? "Headline check on the dashboard" : headlineFull ? HEADLINE_LIMIT_MESSAGE : "Show on the dashboard"}
          >
            <button
              type="button"
              aria-pressed={setting.is_headline}
              aria-label={`Headline check: ${setting.display_name}`}
              disabled={busy !== null}
              onClick={headline}
              className={cn(
                "grid size-8 cursor-pointer place-items-center rounded-control transition-colors",
                setting.is_headline ? "text-warning hover:bg-warning-soft" : "text-fg-3 hover:bg-surface-3 hover:text-fg",
                focusRing,
              )}
            >
              <motion.span
                key={String(setting.is_headline)}
                initial={{ scale: 0.6, rotate: -30 }}
                animate={{ scale: 1, rotate: 0 }}
                transition={{ type: "spring", stiffness: 500, damping: 20 }}
              >
                <Star className="size-4" fill={setting.is_headline ? "currentColor" : "none"} aria-hidden />
              </motion.span>
            </button>
          </Tooltip>
          <SwitchControl
            checked={setting.enabled}
            disabled={busy === "toggle"}
            onCheckedChange={toggle}
            aria-label={`${setting.display_name} ${setting.enabled ? "on" : "off"}`}
            className="mx-1"
          />
          {fields.length > 0 && (
            <IconButton
              label={open ? `Hide ${setting.display_name} settings` : `${setting.display_name} settings`}
              aria-expanded={open}
              aria-controls={panelId}
              onClick={() => setOpen((o) => !o)}
              className="size-8"
            >
              <ChevronDown className={cn("size-4 transition-transform duration-200", open && "rotate-180")} aria-hidden />
            </IconButton>
          )}
        </div>
      </div>
      <AnimatePresence initial={false}>
        {(open || dirty) && fields.length > 0 && (
          <motion.div
            id={panelId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="mx-4 divide-y divide-line border-t border-line">
              {fields.map((f) => (
                <SettingField
                  key={f.key}
                  field={f}
                  value={draft[f.key]}
                  error={errors[f.key] ?? serverErrors[f.key] ?? null}
                  models={models}
                  adjusted={(setting.adjusted_fields ?? []).includes(f.key)}
                  onChange={(v) => {
                    setDraft((d) => ({ ...d, [f.key]: v }));
                    setServerErrors((s) => ({ ...s, [f.key]: "" }));
                  }}
                />
              ))}
            </div>
            <AnimatePresence initial={false}>
              {dirty && (
                <motion.div
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center justify-end gap-2 border-t border-line bg-surface-2/50 px-4 py-2.5"
                >
                  <span className="mr-auto text-[13px] text-fg-3">Unsaved changes to this check</span>
                  <Button size="sm" icon={<RotateCcw aria-hidden />} onClick={() => setDraft(saved)} disabled={busy === "save"}>
                    Discard
                  </Button>
                  <Button size="sm" variant="primary" onClick={save} disabled={invalid} pending={busy === "save"}>
                    Save settings
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}
