import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CircleAlert, FileJson, Info, PenLine, Save, Tag } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import {
  createTool,
  type EndCallConfig,
  type HttpToolConfig,
  type PressDigitConfig,
  type Tool,
  type ToolDraft,
  toolKeys,
  type ToolPreset,
  type ToolType,
  type TransferConfig,
  updateTool,
  useToolPresets,
} from "../../../api/tools";
import { Button, Drawer, Field, Input, Skeleton, Textarea, cn, toast } from "../../../components";
import { EndCallForm } from "./forms/EndCallForm";
import { draftErrors, exampleArguments } from "./forms/fieldRules";
import { FormSection } from "./forms/FormSection";
import { HttpToolForm } from "./forms/HttpToolForm";
import { PressDigitForm } from "./forms/PressDigitForm";
import { TransferForm } from "./forms/TransferForm";
import { TestRunPanel } from "./TestRunPanel";
import { DEFAULT_CONFIGS, TOOL_META, TOOL_TYPES, ToolTile } from "./toolMeta";

function blank(type: ToolType): ToolDraft {
  return { type, name: "", description: "", config: structuredClone(DEFAULT_CONFIGS[type]), mock_response: null };
}

function fromTool(tool: Tool): ToolDraft {
  return {
    type: tool.type,
    name: tool.name,
    description: tool.description,
    config: { ...structuredClone(DEFAULT_CONFIGS[tool.type]), ...structuredClone(tool.config) },
    mock_response: tool.mock_response,
  };
}

/** Pretty JSON; schemas list type, properties and required first (stored JSON sorts keys). */
function jsonText(value: unknown, empty = ""): string {
  if (value == null) return empty;
  if (typeof value === "object" && !Array.isArray(value)) {
    const v = value as Record<string, unknown>;
    const order = ["type", "description", "properties", "required"];
    const keys = [...order.filter((k) => k in v), ...Object.keys(v).filter((k) => !order.includes(k))];
    return JSON.stringify(Object.fromEntries(keys.map((k) => [k, v[k]])), null, 2);
  }
  return JSON.stringify(value, null, 2);
}

/** The payload the API takes: parsed JSON fields, secret headers without masks. */
function payload(draft: ToolDraft, parametersText: string, bodyText: string): ToolDraft {
  if (draft.type !== "http") return { ...draft, mock_response: null };
  const c = draft.config as HttpToolConfig;
  const config: HttpToolConfig = {
    ...c,
    parameters: JSON.parse(parametersText) as Record<string, unknown>,
    body_template: bodyText.trim() ? (JSON.parse(bodyText) as unknown) : null,
    headers: (c.headers ?? []).map((h) =>
      h.secret
        ? { name: h.name, secret: true, ...(h.value ? { value: h.value } : { secret_ref: h.secret_ref }) }
        : { name: h.name, value: h.value ?? "", secret: false },
    ),
  };
  return { ...draft, config, mock_response: draft.mock_response?.trim() ? draft.mock_response : null };
}

function PresetCard({ preset, onPick }: { preset: ToolPreset; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      className="group flex min-w-0 items-start gap-3 rounded-panel border border-line bg-surface p-4 text-left shadow-1 transition-[transform,box-shadow,border-color] duration-200 hover:border-accent/45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      <ToolTile type={preset.type} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-[14px] font-semibold text-fg">{preset.title}</span>
        <span className="text-[13px] leading-snug text-fg-2">{preset.summary}</span>
        <span className="mt-1 font-mono text-[12px] text-fg-3">{preset.tool.name}</span>
      </span>
      <ArrowRight
        className="mt-1 size-4 shrink-0 text-fg-3 opacity-0 transition-[opacity,transform] duration-200 group-hover:translate-x-0.5 group-hover:opacity-100"
        aria-hidden
      />
    </button>
  );
}

function Picker({ onPick }: { onPick: (draft: ToolDraft) => void }) {
  const presets = useToolPresets();
  return (
    <div className="flex flex-col gap-6">
      <FormSection
        title="Start from a preset"
        icon={<PenLine aria-hidden />}
        description="Prefilled with sensible defaults; you can change everything before saving."
      >
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2">
          {presets.isPending
            ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[104px] w-full rounded-panel" />)
            : (presets.data ?? []).map((p) => (
                <PresetCard
                  key={p.preset_id}
                  preset={p}
                  onPick={() =>
                    onPick({
                      ...blank(p.type),
                      ...structuredClone(p.tool),
                      config: { ...structuredClone(DEFAULT_CONFIGS[p.type]), ...structuredClone(p.tool.config) },
                    })
                  }
                />
              ))}
        </div>
      </FormSection>
      <FormSection title="Or start blank" icon={<Tag aria-hidden />}>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {TOOL_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => onPick(blank(t))}
              className="flex flex-col items-start gap-2 rounded-panel border border-line bg-surface p-3 text-left transition-[transform,box-shadow,border-color] duration-200 hover:border-accent/45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <ToolTile type={t} size="sm" />
              <span className="flex flex-col gap-0.5">
                <span className="text-[13px] font-medium text-fg">{TOOL_META[t].label}</span>
                <span className="text-[12px] leading-snug text-fg-3">{TOOL_META[t].summary}</span>
              </span>
            </button>
          ))}
        </div>
      </FormSection>
    </div>
  );
}

/**
 * Create or edit a tool (T032, T088, T095). New tools start from a preset or a blank type; the form
 * checks names, numbers and URLs as they are typed and keeps Save disabled while anything is
 * invalid. HTTP tools add a canned response for simulations and a test run.
 */
export function ToolEditorDialog({
  open,
  onOpenChange,
  tool,
  onSaved,
  allowHttp = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tool: Tool | null;
  onSaved: (tool: Tool, created: boolean) => void;
  allowHttp?: boolean;
}) {
  const qc = useQueryClient();
  const initial = useMemo(() => (tool ? fromTool(tool) : null), [tool]);
  const [draft, setDraft] = useState<ToolDraft | null>(initial);
  const [parametersText, setParametersText] = useState(() => jsonText((initial?.config as HttpToolConfig | undefined)?.parameters, "{}"));
  const [bodyText, setBodyText] = useState(() => jsonText((initial?.config as HttpToolConfig | undefined)?.body_template));
  const [serverIssues, setServerIssues] = useState<{ pointer: string; message: string }[]>([]);

  const pick = (d: ToolDraft) => {
    setDraft(d);
    setParametersText(jsonText((d.config as HttpToolConfig).parameters, "{}"));
    setBodyText(jsonText((d.config as HttpToolConfig).body_template));
    setServerIssues([]);
  };

  const errors = draft ? draftErrors(draft, draft.type === "http" ? { parameters: parametersText, body: bodyText } : {}, allowHttp) : {};
  const invalid = Object.keys(errors).length > 0;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(initial);

  const save = useMutation({
    mutationFn: async () => {
      const body = payload(draft!, parametersText, bodyText);
      return tool ? updateTool(tool.id, body) : createTool(body);
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: toolKeys.all });
      toast({ tone: "success", title: tool ? "Tool saved" : "Tool created", description: `${saved.name} is ready to use.` });
      onSaved(saved, !tool);
      onOpenChange(false);
    },
    onError: (e) => {
      if (isApiError(e) && e.status === 422 && e.problem.errors?.length) setServerIssues(e.problem.errors);
      else toast({ tone: "error", title: "Not saved", description: problemMessage(e, "tool") });
    },
  });

  const set = (patch: Partial<ToolDraft>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const setConfig = (config: ToolDraft["config"]) => set({ config });
  const meta = draft ? TOOL_META[draft.type] : null;

  return (
    <Drawer
      open={open}
      onOpenChange={(o) => !save.isPending && onOpenChange(o)}
      width="xl"
      title={tool ? `Edit ${tool.name}` : draft ? `New ${meta!.label.toLowerCase()} tool` : "New tool"}
      meta={tool ? tool.id : draft ? meta!.summary : "Pick a preset or a type to begin."}
      footer={
        draft ? (
          <>
            {!tool && (
              <Button variant="ghost" icon={<ArrowLeft aria-hidden />} className="mr-auto" onClick={() => setDraft(null)}>
                Change type
              </Button>
            )}
            <Button onClick={() => onOpenChange(false)} disabled={save.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              icon={<Save aria-hidden />}
              pending={save.isPending}
              disabled={invalid || (Boolean(tool) && !dirty)}
              onClick={() => save.mutate()}
            >
              {tool ? "Save tool" : "Create tool"}
            </Button>
          </>
        ) : undefined
      }
    >
      <AnimatePresence mode="wait" initial={false}>
        {!draft ? (
          <motion.div
            key="pick"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.18 }}
          >
            <Picker onPick={pick} />
          </motion.div>
        ) : (
          <motion.div
            key="form"
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 8 }}
            transition={{ duration: 0.18 }}
            className="flex flex-col gap-5 pb-2"
          >
            {tool && tool.usage_count > 0 && (
              <div className="flex items-start gap-2.5 rounded-panel bg-accent-soft/60 px-4 py-3 text-[13px] text-fg">
                <Info className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
                <p>
                  Used by {tool.usage_count} {tool.usage_count === 1 ? "agent" : "agents"}. Their drafts pick up your changes; published versions keep
                  the definition they were published with until you publish again.
                </p>
              </div>
            )}
            {serverIssues.length > 0 && (
              <div role="alert" className="flex items-start gap-2.5 rounded-panel bg-danger-soft px-4 py-3 text-[13px] text-danger-text">
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <ul className="flex flex-col gap-0.5">
                  {serverIssues.map((i) => (
                    <li key={i.pointer + i.message}>
                      <span className="font-mono">{i.pointer.replace(/^\//, "")}</span>: {i.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <FormSection title="Basics" icon={<Tag aria-hidden />}>
              <Field
                label="Name"
                error={draft.name ? errors.name : null}
                hint="What the model calls the tool: lowercase letters, digits and underscores."
              >
                {({ id, describedBy, invalid: bad }) => (
                  <Input
                    id={id}
                    className="font-mono"
                    spellCheck={false}
                    maxLength={64}
                    placeholder={meta!.namePlaceholder}
                    aria-describedby={describedBy}
                    aria-invalid={bad}
                    value={draft.name}
                    onChange={(e) => set({ name: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
                  />
                )}
              </Field>
              <Field label="When to use it" hint="The model reads this to decide when to call the tool. Be specific.">
                {({ id, describedBy }) => (
                  <Textarea
                    id={id}
                    maxLength={1000}
                    className="min-h-20"
                    placeholder={meta!.descriptionPlaceholder}
                    aria-describedby={describedBy}
                    value={draft.description}
                    onChange={(e) => set({ description: e.target.value })}
                  />
                )}
              </Field>
            </FormSection>

            {draft.type === "end_call" && <EndCallForm config={draft.config as EndCallConfig} onChange={setConfig} />}
            {draft.type === "transfer_call" && <TransferForm config={draft.config as TransferConfig} errors={errors} onChange={setConfig} />}
            {draft.type === "press_digit" && <PressDigitForm config={draft.config as PressDigitConfig} errors={errors} onChange={setConfig} />}
            {draft.type === "http" && (
              <>
                <HttpToolForm
                  config={draft.config as HttpToolConfig}
                  errors={errors}
                  onChange={setConfig}
                  parametersText={parametersText}
                  onParametersText={setParametersText}
                  bodyText={bodyText}
                  onBodyText={setBodyText}
                  allowHttp={allowHttp}
                />
                <FormSection
                  title="Canned response"
                  icon={<FileJson aria-hidden />}
                  description="Returned instead of calling your API when the agent runs in a simulation, so tests never create real bookings."
                >
                  <Field label="Canned response" hideLabel hint="Usually the JSON your API would answer with.">
                    {({ id, describedBy }) => (
                      <Textarea
                        id={id}
                        spellCheck={false}
                        maxLength={16384}
                        aria-describedby={describedBy}
                        className={cn("min-h-24 font-mono text-[13px]")}
                        placeholder={'{ "slots": ["09:30", "11:00"] }'}
                        value={draft.mock_response ?? ""}
                        onChange={(e) => set({ mock_response: e.target.value })}
                      />
                    )}
                  </Field>
                </FormSection>
                <TestRunPanel
                  toolId={tool?.id ?? null}
                  draft={invalid ? draft : payload(draft, parametersText, bodyText)}
                  useSaved={Boolean(tool) && !dirty}
                  initialArguments={(() => {
                    try {
                      return exampleArguments(JSON.parse(parametersText) as Record<string, unknown>);
                    } catch {
                      return {};
                    }
                  })()}
                  disabled={invalid && !(tool && !dirty)}
                />
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </Drawer>
  );
}
