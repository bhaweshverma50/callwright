import { GitBranch, Plus, Tag, Trash2, Workflow } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { ConditionConfig, FlowEdge } from "../../../../api/flows";
import { Button, Field, IconButton, Input, Segmented, Textarea } from "../../../../components";
import { edgeText } from "../../canvas/edges/TransitionEdge";
import { categoryNameError } from "./fieldRules";
import { Group, issueFor, type FormProps } from "./shared";

/**
 * Condition node (FR-013, FR-043, T105). Classify: the model picks one category, one handle and
 * connection each; names are checked inline and renaming carries the connection. Rule: ordered
 * comparisons live on the connections leaving the Rule handle, then Otherwise.
 */
export function ConditionForm({
  config,
  onChange,
  issues,
  outgoing,
  onRenameCategory,
  onSelectEdge,
}: FormProps<ConditionConfig> & {
  outgoing: FlowEdge[];
  onRenameCategory: (from: string, to: string, next: ConditionConfig) => void;
  onSelectEdge: (id: string) => void;
}) {
  const set = (patch: Partial<ConditionConfig>) => onChange({ ...config, ...patch });
  const cats = config.categories ?? [];
  const [draft, setDraft] = useState("");
  const [names, setNames] = useState<Record<number, string>>({});
  const draftError = draft
    ? categoryNameError(
        draft.trim(),
        cats.map((c) => c.name),
      )
    : null;

  const add = () => {
    const name = draft.trim();
    if (
      !name ||
      categoryNameError(
        name,
        cats.map((c) => c.name),
      )
    )
      return;
    set({ categories: [...cats, { name, description: "" }] });
    setDraft("");
  };

  return (
    <>
      <Group title="How it routes" icon={<GitBranch aria-hidden />}>
        <Segmented
          fill
          aria-label="Condition kind"
          value={config.kind}
          onValueChange={(kind) => set({ kind })}
          options={[
            { value: "classify", label: "Classify", icon: <Tag aria-hidden /> },
            { value: "rule", label: "Rules", icon: <Workflow aria-hidden /> },
          ]}
        />
        <p className="text-[13px] leading-relaxed text-fg-3">
          {config.kind === "classify"
            ? "The model reads the conversation and picks one category, silently. Each category gets its own connection."
            : "Checks variables in order; the first rule that matches wins, otherwise the Otherwise connection is followed. No model runs."}
        </p>
      </Group>
      {config.kind === "classify" ? (
        <Group title="Categories" description="2 to 20. Each needs exactly one connection from its handle.">
          <ul className="flex flex-col gap-2.5">
            <AnimatePresence initial={false}>
              {cats.map((c, i) => {
                const others = cats.filter((_, j) => j !== i).map((x) => x.name);
                const typed = names[i] ?? c.name;
                const err = categoryNameError(typed.trim(), others) ?? issueFor(issues, `categories.${i}.name`);
                return (
                  <motion.li
                    key={i}
                    layout
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, height: 0 }}
                    className="rounded-control border border-line bg-surface-2/40 p-2.5"
                  >
                    <div className="flex items-center gap-1.5">
                      <Input
                        inputSize="sm"
                        aria-label={`Category ${i + 1} name`}
                        aria-invalid={Boolean(err) || undefined}
                        value={typed}
                        onChange={(e) => setNames((n) => ({ ...n, [i]: e.target.value }))}
                        onBlur={() => {
                          const next = typed.trim();
                          setNames((n) => {
                            const { [i]: _, ...rest } = n;
                            return rest;
                          });
                          if (next === c.name || categoryNameError(next, others)) return;
                          const categories = cats.map((x, j) => (j === i ? { ...x, name: next } : x));
                          onRenameCategory(c.name, next, { ...config, categories });
                        }}
                        className="font-medium"
                      />
                      <IconButton
                        label={`Remove ${c.name}`}
                        className="size-8 shrink-0"
                        onClick={() => set({ categories: cats.filter((_, j) => j !== i) })}
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                      </IconButton>
                    </div>
                    {err && <p className="mt-1.5 text-[12px] text-danger-text">{err}</p>}
                    <Textarea
                      aria-label={`What ${c.name} means`}
                      rows={2}
                      value={c.description}
                      placeholder="When does this category fit?"
                      onChange={(e) => set({ categories: cats.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)) })}
                      className="mt-2 min-h-0 text-[13px]"
                    />
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
          <Field label="New category" hideLabel error={draftError}>
            {({ id, describedBy, invalid }) => (
              <div className="flex gap-2">
                <Input
                  id={id}
                  inputSize="sm"
                  value={draft}
                  placeholder="Add a category, for example Billing"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                />
                <Button size="sm" icon={<Plus aria-hidden />} onClick={add} disabled={!draft.trim() || Boolean(draftError) || cats.length >= 20}>
                  Add
                </Button>
              </div>
            )}
          </Field>
          <Field label="Extra guidance for the model (optional)" hint="Read with the conversation when choosing.">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                rows={2}
                value={config.instructions}
                onChange={(e) => set({ instructions: e.target.value })}
                aria-describedby={describedBy}
              />
            )}
          </Field>
        </Group>
      ) : (
        <Group title="Rules" description="Connect the Rule handle once per rule, then set each rule on its connection.">
          {outgoing.filter((e) => e.trigger === "rule" || e.trigger === "else").length === 0 ? (
            <p className="rounded-control border border-dashed border-line-strong px-3 py-3 text-[13px] text-fg-3">
              No rules yet. Drag from the Rule handle to the next step.
            </p>
          ) : (
            <ol className="flex flex-col gap-1.5">
              {[...outgoing.filter((e) => e.trigger === "rule"), ...outgoing.filter((e) => e.trigger === "else")].map((e, i) => (
                <li key={e.id}>
                  <button
                    type="button"
                    onClick={() => onSelectEdge(e.id)}
                    className="flex w-full cursor-pointer items-center gap-2.5 rounded-control border border-line bg-surface px-3 py-2 text-left text-[13px] transition-colors hover:border-line-strong hover:bg-surface-2/60"
                  >
                    <span className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-3 font-mono text-[11px] text-fg-2">
                      {e.trigger === "else" ? "∗" : i + 1}
                    </span>
                    <span className="min-w-0 truncate font-mono text-fg">{edgeText(e)}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </Group>
      )}
    </>
  );
}
