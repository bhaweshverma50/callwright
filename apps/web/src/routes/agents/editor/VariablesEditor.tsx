import { Braces, Plus, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { Badge, Button, IconButton, InfoTip, Input, TruncatedText } from "../../../components";
import { RESERVED_VARIABLES, scanPlaceholders, variableNameProblem } from "../../../lib/agentVariables";
import { fieldId } from "../versions/versionLabels";
import { FieldError, StackRow } from "./fields";
import type { AgentDraft } from "./useAgentDraft";

/**
 * Dynamic variables (FR-008, US1.4, US1.10). Names typed as `{{name}}` in the prompt or greeting
 * join the list on their own; names added by hand are checked against the naming rule first.
 * Each row shows whether the variable is used and whether it has a default.
 */
export function VariablesEditor({ draft }: { draft: AgentDraft }) {
  const { config } = draft;
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const used = useMemo(() => scanPlaceholders(config.prompt, config.begin_message), [config.prompt, config.begin_message]);
  const names = config.dynamic_variables.map((v) => v.name);
  const addId = "f-dynamic_variables-new";

  const add = () => {
    const n = name.trim();
    const p = variableNameProblem(n, names);
    setProblem(p);
    if (p) return;
    draft.update((c) => void c.dynamic_variables.push({ name: n, default: null }));
    setName("");
  };

  return (
    <StackRow
      icon={<Braces />}
      label="Variables"
      htmlFor={addId}
      description="Values each call can fill in, such as a customer's name. Calls that leave one out use its default."
      hint={
        <>
          Write <span className="font-mono">{"{{name}}"}</span> in the prompt or greeting and the variable is added here. Built-in values are filled
          in for every call: {RESERVED_VARIABLES.join(", ")}.
        </>
      }
    >
      <div className="overflow-hidden rounded-control border border-line">
        {config.dynamic_variables.length === 0 ? (
          <p className="bg-surface-2/50 px-4 py-3.5 text-[13px] text-fg-3">
            No variables yet. Type <span className="font-mono text-fg-2">{"{{customer_name}}"}</span> in the prompt to add one.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            <AnimatePresence initial={false}>
              {config.dynamic_variables.map((v, i) => {
                const pointer = `/dynamic_variables[${v.name}]`;
                const inUse = used.names.includes(v.name);
                const noDefault = !v.default;
                const err = draft.errorFor(`${pointer}/name`) ?? draft.errorFor(`${pointer}/default`);
                return (
                  <motion.li
                    key={v.name}
                    layout
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.18 }}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 px-3 py-2.5 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto]"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <code className="min-w-0 rounded-inline bg-accent-soft/70 px-1.5 py-0.5 font-mono text-[13px] text-accent-text">
                        <TruncatedText>{`{{${v.name}}}`}</TruncatedText>
                      </code>
                      {!inUse && (
                        <Badge tone="neutral" className="shrink-0">
                          Unused
                        </Badge>
                      )}
                    </div>
                    <IconButton
                      label={`Remove ${v.name}`}
                      className="size-8 sm:order-3"
                      onClick={() => draft.update((c) => void c.dynamic_variables.splice(i, 1))}
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </IconButton>
                    <div className="col-span-2 flex min-w-0 flex-col gap-1 sm:order-2 sm:col-span-1">
                      <Input
                        id={fieldId(`${pointer}/default`)}
                        inputSize="sm"
                        aria-label={`Default for ${v.name}`}
                        placeholder={inUse ? "No default: calls must supply it" : "Default value"}
                        value={v.default ?? ""}
                        aria-invalid={Boolean(err)}
                        onChange={(e) => draft.update((c) => void (c.dynamic_variables[i]!.default = e.target.value || null))}
                        onBlur={() => draft.touch(`${pointer}/default`)}
                        className={noDefault && inUse ? "border-warning/60" : undefined}
                      />
                      <FieldError message={err} />
                    </div>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
        <div className="flex flex-col gap-1.5 border-t border-line bg-surface-2/50 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <Input
              id={addId}
              inputSize="sm"
              className="min-w-0 flex-1 font-mono"
              placeholder="variable_name"
              aria-label="New variable name"
              value={name}
              aria-invalid={Boolean(problem)}
              onChange={(e) => {
                setName(e.target.value);
                if (problem) setProblem(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add();
                }
              }}
            />
            <Button size="sm" icon={<Plus aria-hidden />} onClick={add}>
              Add variable
            </Button>
          </div>
          <FieldError message={problem} />
        </div>
      </div>
      {used.invalid.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-warning-text">
          Not valid variable names, spoken as written:
          {used.invalid.map((s) => (
            <code key={s} className="rounded-inline bg-warning-soft px-1.5 font-mono">
              {s}
            </code>
          ))}
          <InfoTip label="About variable names">Names start with a letter or underscore and use only letters, digits and underscores.</InfoTip>
        </p>
      )}
    </StackRow>
  );
}
