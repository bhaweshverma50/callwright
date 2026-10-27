import { useQueryClient } from "@tanstack/react-query";
import { Hash, ListChecks, Plus, ToggleLeft, Type, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type KeyboardEvent } from "react";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import {
  createVariable,
  qualityKeys,
  updateVariable,
  type AnalysisVariable,
  type AnalysisVariableInput,
  type VariableType,
} from "../../../api/quality";
import { Button, Dialog, Field, Input, Segmented, Textarea, toast } from "../../../components";
import { NAME_RULE, toVariableName } from "./variableName";

export const TYPE_LABELS: Record<VariableType, string> = { boolean: "Yes or no", string: "Text", number: "Number", choice: "One of a set" };
export const TYPE_ICONS = { boolean: ToggleLeft, string: Type, number: Hash, choice: ListChecks } as const;

const MAX_DESCRIPTION = 500;
const MAX_CHOICES = 20;

/** Problems with the form as it stands; "Save variable" stays disabled while any exist (FR-046). */
export function variableFormErrors(v: { name: string; type: VariableType; description: string; choices: string[] }) {
  return {
    name: v.name ? null : NAME_RULE,
    description: !v.description.trim() ? "Describe what to capture." : v.description.length > MAX_DESCRIPTION ? "Keep it under 500 characters." : null,
    choices:
      v.type !== "choice"
        ? null
        : v.choices.length < 2
          ? "Add at least 2 choices."
          : v.choices.length > MAX_CHOICES
            ? "Up to 20 choices."
            : null,
  };
}

/**
 * "Add variable" and edit (US1 scenarios 7 and 8, T090): what the operator types becomes a
 * snake_case name shown before save; the choices field exists only for the fixed-set type, and
 * no choices are sent for the other types.
 */
export function AddVariableDialog({
  agentId,
  open,
  onOpenChange,
  existing,
}: {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing?: AnalysisVariable | null;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      icon={<ListChecks aria-hidden />}
      title={existing ? `Edit ${existing.name}` : "Add variable"}
      description="A field the model fills from every call of this agent, or leaves as not found."
    >
      {open && <VariableForm key={existing?.id ?? "new"} agentId={agentId} existing={existing ?? null} onDone={() => onOpenChange(false)} />}
    </Dialog>
  );
}

function VariableForm({ agentId, existing, onDone }: { agentId: string; existing: AnalysisVariable | null; onDone: () => void }) {
  const qc = useQueryClient();
  const [typed, setTyped] = useState(existing?.name ?? "");
  const [type, setType] = useState<VariableType>(existing?.type ?? "boolean");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [choices, setChoices] = useState<string[]>(existing?.choices ?? []);
  const [choiceText, setChoiceText] = useState("");
  const [touched, setTouched] = useState({ name: false, description: false });
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const name = toVariableName(typed);
  const errors = variableFormErrors({ name, type, description, choices });
  const valid = !errors.name && !errors.description && !errors.choices;
  const choiceDuplicate = choices.includes(choiceText.trim());

  const addChoice = () => {
    const c = choiceText.trim().slice(0, 64);
    if (!c || choices.includes(c) || choices.length >= MAX_CHOICES) return;
    setChoices([...choices, c]);
    setChoiceText("");
  };
  const onChoiceKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addChoice();
    }
  };

  const save = async () => {
    if (!valid) return;
    setSaving(true);
    setServerErrors({});
    const body: AnalysisVariableInput = { name, type, description: description.trim(), ...(type === "choice" ? { choices } : {}) };
    try {
      if (existing) await updateVariable(existing.id, { ...body, choices: type === "choice" ? choices : null });
      else await createVariable(agentId, body);
      await qc.invalidateQueries({ queryKey: qualityKeys.variables(agentId) });
      toast({ tone: "success", title: existing ? `Saved ${name}` : `Added ${name}`, description: "Calls that end from now on extract it." });
      onDone();
    } catch (e) {
      if (isApiError(e) && e.status === 409) setServerErrors({ name: e.problem.detail ?? "That name is already used on this agent." });
      else if (isApiError(e) && e.status === 422) {
        const out: Record<string, string> = {};
        for (const fe of e.problem.errors ?? []) out[fe.pointer.split("/").pop() ?? ""] ??= fe.message;
        setServerErrors(out);
      } else toast({ tone: "error", title: "Could not save the variable", description: problemMessage(e, "agent") });
    } finally {
      setSaving(false);
    }
  };

  const nameError = serverErrors.name ?? (touched.name && typed && errors.name ? errors.name : null);
  return (
    <form
      className="flex flex-col gap-5 pb-2"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <Field
        label="Name"
        error={nameError}
        hint={
          name ? (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              Saved as
              <code data-testid="variable-name" className="rounded-inline bg-accent-soft px-1.5 py-0.5 font-mono text-[12px] text-accent-text">
                {name}
              </code>
            </span>
          ) : (
            NAME_RULE
          )
        }
      >
        {(ids) => (
          <Input
            id={ids.id}
            aria-describedby={ids.describedBy}
            aria-invalid={ids.invalid}
            value={typed}
            autoFocus
            placeholder="For example Appointment booked"
            onChange={(e) => {
              setTyped(e.target.value);
              setServerErrors((s) => ({ ...s, name: "" }));
            }}
            onBlur={() => setTouched((t) => ({ ...t, name: true }))}
          />
        )}
      </Field>

      <div className="flex flex-col gap-1.5">
        <span id="var-type-label" className="text-[13px] font-medium text-fg">
          Type
        </span>
        <Segmented
          aria-labelledby="var-type-label"
          value={type}
          onValueChange={(t) => setType(t)}
          fill
          options={(Object.keys(TYPE_LABELS) as VariableType[]).map((t) => {
            const Icon = TYPE_ICONS[t];
            return { value: t, label: TYPE_LABELS[t], icon: <Icon aria-hidden /> };
          })}
        />
      </div>

      <Field
        label="Description"
        error={serverErrors.description ?? (touched.description ? errors.description : null)}
        hint="Tell the model exactly what to capture and when to leave it as not found."
        aside={<span className="font-mono text-[11.5px] text-fg-3 tnum">{`${description.length}/${MAX_DESCRIPTION}`}</span>}
      >
        {(ids) => (
          <Textarea
            id={ids.id}
            aria-describedby={ids.describedBy}
            aria-invalid={ids.invalid}
            value={description}
            maxLength={MAX_DESCRIPTION}
            className="min-h-20"
            placeholder="True if the caller confirmed a time slot."
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, description: true }))}
          />
        )}
      </Field>

      <AnimatePresence initial={false}>
        {type === "choice" && (
          <motion.div
            key="choices"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <Field
              label="Choices"
              error={serverErrors.choices ?? (choiceDuplicate && choiceText ? "That choice is already in the list." : null)}
              hint={errors.choices ?? `${choices.length} of ${MAX_CHOICES}. Answers outside the set are stored as not found.`}
            >
              {(ids) => (
                <div className="flex flex-col gap-2.5">
                  <div className="flex gap-2">
                    <Input
                      id={ids.id}
                      aria-describedby={ids.describedBy}
                      value={choiceText}
                      maxLength={64}
                      placeholder="Type a choice and press Enter"
                      onChange={(e) => setChoiceText(e.target.value)}
                      onKeyDown={onChoiceKey}
                    />
                    <Button type="button" icon={<Plus aria-hidden />} onClick={addChoice} disabled={!choiceText.trim() || choiceDuplicate}>
                      Add
                    </Button>
                  </div>
                  {choices.length > 0 && (
                    <ul className="flex flex-wrap gap-1.5" aria-label="Choices">
                      <AnimatePresence initial={false}>
                        {choices.map((c) => (
                          <motion.li
                            key={c}
                            layout
                            initial={{ opacity: 0, scale: 0.9 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.9 }}
                            className="inline-flex h-7 items-center gap-1 rounded-full border border-line-strong bg-surface-2 pl-2.5 pr-1 text-[12.5px] text-fg"
                          >
                            {c}
                            <button
                              type="button"
                              aria-label={`Remove ${c}`}
                              onClick={() => setChoices(choices.filter((x) => x !== c))}
                              className="grid size-5 cursor-pointer place-items-center rounded-full text-fg-3 hover:bg-surface-3 hover:text-fg"
                            >
                              <X className="size-3" aria-hidden />
                            </button>
                          </motion.li>
                        ))}
                      </AnimatePresence>
                    </ul>
                  )}
                </div>
              )}
            </Field>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="-mx-5 mt-1 flex justify-end gap-2 border-t border-line px-5 pt-3.5">
        <Button type="button" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!valid} pending={saving}>
          Save variable
        </Button>
      </div>
    </form>
  );
}
