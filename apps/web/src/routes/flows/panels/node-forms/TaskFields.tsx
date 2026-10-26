import { Braces, List, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { TaskField } from "../../../../api/flows";
import { Button, IconButton, Input, Segmented, Select, Switch, Textarea } from "../../../../components";
import { fieldNameError, jsonError, toVariableName } from "./fieldRules";

const TYPES = [
  { value: "string", label: "Text" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "True or false" },
  { value: "enum", label: "One of a list" },
];

export function fieldsToSchema(fields: TaskField[]): string {
  const properties: Record<string, unknown> = {};
  for (const f of fields)
    properties[f.name] =
      f.type === "enum" ? { type: "string", enum: f.enum_values ?? [], description: f.description } : { type: f.type, description: f.description };
  return JSON.stringify({ type: "object", properties, required: fields.filter((f) => f.required).map((f) => f.name) }, null, 2);
}

export function schemaToFields(text: string): TaskField[] | null {
  try {
    const schema = JSON.parse(text) as { properties?: Record<string, { type?: string; enum?: string[]; description?: string }>; required?: string[] };
    if (!schema || typeof schema !== "object" || !schema.properties) return null;
    return Object.entries(schema.properties).map(([name, p]) => ({
      name,
      type: p.enum ? "enum" : ((["string", "number", "boolean"].includes(p.type ?? "") ? p.type : "string") as TaskField["type"]),
      description: p.description ?? "",
      required: (schema.required ?? []).includes(name),
      ...(p.enum ? { enum_values: p.enum } : {}),
    }));
  } catch {
    return null;
  }
}

/**
 * Task fields (FR-012, FR-055, T107): a field list or JSON Schema text. JSON errors show while
 * typing with the line; switching views keeps the fields.
 */
export function TaskFields({ fields, onChange, error }: { fields: TaskField[]; onChange: (f: TaskField[]) => void; error: string | null }) {
  const [view, setView] = useState<"list" | "json">("list");
  const [text, setText] = useState(() => fieldsToSchema(fields));
  const textError =
    view === "json" ? (jsonError(text, { required: true }) ?? (schemaToFields(text) ? null : 'Use a JSON Schema object with "properties".')) : null;
  const set = (i: number, patch: Partial<TaskField>) => onChange(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="flex flex-col gap-3">
      <Segmented
        size="sm"
        className="w-fit"
        aria-label="Field editor"
        value={view}
        onValueChange={(v) => {
          if (v === "json") setText(fieldsToSchema(fields));
          setView(v);
        }}
        options={[
          { value: "list", label: "Fields", icon: <List aria-hidden /> },
          { value: "json", label: "JSON Schema", icon: <Braces aria-hidden /> },
        ]}
      />
      {view === "json" ? (
        <>
          <Textarea
            aria-label="Task JSON Schema"
            rows={12}
            value={text}
            spellCheck={false}
            className="font-mono text-[12px] leading-relaxed"
            aria-invalid={Boolean(textError) || undefined}
            onChange={(e) => {
              setText(e.target.value);
              const parsed = jsonError(e.target.value, { required: true }) ? null : schemaToFields(e.target.value);
              if (parsed) onChange(parsed);
            }}
          />
          {textError && <p className="text-[12px] text-danger-text">{textError}</p>}
        </>
      ) : (
        <>
          <ul className="flex flex-col gap-2.5">
            {fields.map((f, i) => {
              const nameError = fieldNameError(
                f.name,
                fields.filter((_, j) => j !== i).map((x) => x.name),
              );
              return (
                <li key={i} className="rounded-control border border-line bg-surface-2/40 p-2.5">
                  <div className="flex items-center gap-1.5">
                    <Input
                      inputSize="sm"
                      aria-label={`Field ${i + 1} name`}
                      value={f.name}
                      onChange={(e) => set(i, { name: e.target.value })}
                      onBlur={(e) => set(i, { name: toVariableName(e.target.value) || e.target.value })}
                      aria-invalid={Boolean(nameError) || undefined}
                      className="font-mono"
                    />
                    <Select
                      size="sm"
                      className="w-[132px] shrink-0"
                      value={f.type}
                      onValueChange={(v) => set(i, { type: v as TaskField["type"] })}
                      options={TYPES}
                    />
                    <IconButton
                      label={`Remove ${f.name || "field"}`}
                      className="size-8 shrink-0"
                      onClick={() => onChange(fields.filter((_, j) => j !== i))}
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                    </IconButton>
                  </div>
                  {nameError && <p className="mt-1.5 text-[12px] text-danger-text">{nameError}</p>}
                  <Input
                    inputSize="sm"
                    aria-label={`What ${f.name || "this field"} is`}
                    placeholder="Description the agent uses to ask for it"
                    value={f.description}
                    onChange={(e) => set(i, { description: e.target.value })}
                    className="mt-2"
                  />
                  {f.type === "enum" && (
                    <Input
                      inputSize="sm"
                      aria-label={`Allowed values of ${f.name}`}
                      placeholder="Allowed values, separated by commas"
                      value={(f.enum_values ?? []).join(", ")}
                      onChange={(e) =>
                        set(i, {
                          enum_values: e.target.value
                            .split(",")
                            .map((v) => v.trim())
                            .filter(Boolean),
                        })
                      }
                      className="mt-2"
                    />
                  )}
                  <Switch className="mt-2.5" checked={f.required} onCheckedChange={(required) => set(i, { required })} label="Required" />
                </li>
              );
            })}
          </ul>
          <Button
            size="sm"
            className="w-fit"
            icon={<Plus aria-hidden />}
            disabled={fields.length >= 30}
            onClick={() => onChange([...fields, { name: `field_${fields.length + 1}`, type: "string", description: "", required: true }])}
          >
            Add field
          </Button>
        </>
      )}
      {error && <p className="text-[12px] text-danger-text">{error}</p>}
    </div>
  );
}
