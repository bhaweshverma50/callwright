import { Braces, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ExtractConfig, ExtractField } from "../../../../api/flows";
import { Button, Field, IconButton, Input, Select, Textarea } from "../../../../components";
import { fieldNameError } from "./fieldRules";
import { Group, issueFor, type FormProps } from "./shared";
import { FLOW_FIELD_NAME_MAX, toMachineName } from "../../../../lib/machineName";

const TYPES = [
  { value: "string", label: "Text" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "True or false" },
];

/**
 * Extract variable node (FR-015, FR-056): one silent pass that saves named values. A typed
 * name is converted to lowercase with underscores and shown before it is added; the node lists
 * the placeholders it makes available to later steps.
 */
export function ExtractForm({ config, onChange, issues, takenNames }: FormProps<ExtractConfig> & { takenNames: string[] }) {
  const set = (patch: Partial<ExtractConfig>) => onChange({ ...config, ...patch });
  const [typed, setTyped] = useState("");
  const converted = toMachineName(typed, FLOW_FIELD_NAME_MAX);
  const own = config.fields.map((f) => f.name);
  const error = typed.trim() ? fieldNameError(converted, [...own, ...takenNames]) : null;
  const setField = (i: number, patch: Partial<ExtractField>) => set({ fields: config.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const add = () => {
    if (!typed.trim() || error) return;
    set({ fields: [...config.fields, { name: converted, type: "string", description: "" }] });
    setTyped("");
  };
  return (
    <>
      <Group
        title="Variables"
        icon={<Braces aria-hidden />}
        description="Read from the conversation so far, silently. Later steps use them as placeholders."
      >
        {config.fields.length > 0 && (
          <ul className="flex flex-col gap-2.5">
            {config.fields.map((f, i) => (
              <li key={`${f.name}-${i}`} className="rounded-control border border-line bg-surface-2/40 p-2.5">
                <div className="flex items-center gap-1.5">
                  <code className="min-w-0 flex-1 truncate rounded-inline bg-accent-soft px-1.5 py-0.5 font-mono text-[12px] text-accent-text">{`{{${f.name}}}`}</code>
                  <Select
                    size="sm"
                    className="w-[130px]"
                    value={f.type}
                    onValueChange={(v) => setField(i, { type: v as ExtractField["type"] })}
                    options={TYPES}
                  />
                  <IconButton label={`Remove ${f.name}`} className="size-8" onClick={() => set({ fields: config.fields.filter((_, j) => j !== i) })}>
                    <Trash2 className="size-3.5" aria-hidden />
                  </IconButton>
                </div>
                <Textarea
                  aria-label={`What ${f.name} holds`}
                  rows={2}
                  value={f.description}
                  placeholder="What to look for, for example the caller's date of birth"
                  onChange={(e) => setField(i, { description: e.target.value })}
                  className="mt-2 min-h-0 text-[13px]"
                />
                {issueFor(issues, `fields.${i}`) && <p className="mt-1.5 text-[12px] text-danger-text">{issueFor(issues, `fields.${i}`)}</p>}
              </li>
            ))}
          </ul>
        )}
        <Field
          label="Add a variable"
          error={error ?? (config.fields.length ? null : issueFor(issues, "fields"))}
          hint={
            typed.trim() && converted ? (
              <>
                Adds <code className="font-mono text-accent-text">{`{{${converted}}}`}</code>
              </>
            ) : (
              "Type a name, such as Customer Name."
            )
          }
        >
          {({ id, describedBy, invalid }) => (
            <div className="flex gap-2">
              <Input
                id={id}
                inputSize="sm"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
              />
              <Button size="sm" icon={<Plus aria-hidden />} onClick={add} disabled={!typed.trim() || Boolean(error) || config.fields.length >= 30}>
                Add
              </Button>
            </div>
          )}
        </Field>
      </Group>
      <Group title="Instructions (optional)" description="Extra guidance for reading the values.">
        <Textarea aria-label="Extraction instructions" rows={3} value={config.instructions} onChange={(e) => set({ instructions: e.target.value })} />
      </Group>
    </>
  );
}
