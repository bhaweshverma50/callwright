import { BookOpen, ClipboardList, History, MessageSquareText, Repeat } from "lucide-react";
import type { LlmCatalog, VoiceCatalog } from "../../../../api/agents";
import type { ContextStrategy, ConversationalConfig, TaskConfig } from "../../../../api/flows";
import { Field, Input, Segmented, Switch } from "../../../../components";
import { ExpandEditor } from "./ExpandEditor";
import { maxRoundsError } from "./fieldRules";
import { OverridesSection } from "./OverridesSection";
import { Group, issueFor, type FormProps } from "./shared";
import { TaskFields } from "./TaskFields";
import { ToolPicker } from "./ToolPicker";

/**
 * Agent and Task nodes (FR-009 to FR-012): instructions, entry line, context, tools, knowledge
 * search and overrides; a Task also has its fields and maximum rounds.
 */
export function ConversationalForm({
  config,
  onChange,
  issues,
  isTask,
  catalogs,
  onCreateTool,
}: FormProps<ConversationalConfig | TaskConfig> & {
  isTask: boolean;
  catalogs: { llm: LlmCatalog; voice: VoiceCatalog } | null;
  onCreateTool: () => void;
}) {
  const set = (patch: Partial<TaskConfig>) => onChange({ ...config, ...patch } as ConversationalConfig);
  const task = isTask ? (config as TaskConfig) : null;
  const beginWarning = issues.find((i) => i.code === "W_NO_BEGIN_MESSAGE");
  return (
    <>
      <Group
        title="Instructions"
        icon={<MessageSquareText aria-hidden />}
        description="Added after the flow's persona prompt. Use {{name}} for variables."
      >
        <Field
          label="Instructions"
          hideLabel
          error={issueFor(issues, "instructions")}
          hint={`${config.instructions.length.toLocaleString()} / 16,000`}
        >
          {({ id, describedBy, invalid }) => (
            <ExpandEditor
              id={id}
              label="Instructions"
              rows={6}
              maxLength={16000}
              value={config.instructions}
              onChange={(instructions) => set({ instructions })}
              describedBy={describedBy}
              invalid={invalid}
              placeholder={isTask ? "Collect the caller's name and email, confirming spelling." : "Help the caller with billing questions."}
            />
          )}
        </Field>
        <Field
          label="Entry line"
          hint={
            beginWarning
              ? "Without one, the model writes the first line after a move, which takes a moment longer."
              : "Spoken at once when the call moves here."
          }
          error={issueFor(issues, "begin_message")}
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              value={config.begin_message ?? ""}
              placeholder="Sure, let me help with your bill."
              onChange={(e) => set({ begin_message: e.target.value || null })}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              maxLength={500}
            />
          )}
        </Field>
      </Group>
      {task && (
        <Group title="Details to collect" icon={<ClipboardList aria-hidden />} description="Later steps read them as {{task_result.name}}.">
          <TaskFields fields={task.fields} onChange={(fields) => set({ fields })} error={issueFor(issues, "fields")} />
          <Field
            label="Maximum caller rounds"
            hint="After this many answers the step continues with what it has (1 to 20)."
            error={issueFor(issues, "max_rounds") ?? maxRoundsError(task.max_rounds)}
          >
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                type="number"
                inputMode="numeric"
                className="w-28 font-mono tnum"
                value={Number.isFinite(task.max_rounds) ? task.max_rounds : ""}
                onChange={(e) => set({ max_rounds: e.target.value === "" ? Number.NaN : Number(e.target.value) })}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
                prefix={<Repeat className="size-3.5" aria-hidden />}
              />
            )}
          </Field>
        </Group>
      )}
      <Group title="Conversation history" icon={<History aria-hidden />} description="What this step sees when the call moves here.">
        <Segmented
          fill
          size="sm"
          aria-label="Conversation history"
          value={config.context_strategy}
          onValueChange={(context_strategy: ContextStrategy) => set({ context_strategy })}
          options={[
            { value: "inherit", label: "Everything" },
            { value: "summarize", label: "Summary" },
            { value: "reset", label: "Fresh start" },
          ]}
        />
        <p className="text-[12.5px] leading-relaxed text-fg-3">
          {config.context_strategy === "inherit"
            ? "The whole conversation so far."
            : config.context_strategy === "summarize"
              ? "A short summary kept up to date in the background, plus the last two turns. No pause at the move."
              : "No earlier turns; only the persona prompt, these instructions and the details collected."}
        </p>
      </Group>
      <ToolPicker value={config.tool_ids} onChange={(tool_ids) => set({ tool_ids })} onCreateTool={onCreateTool} />
      <Group title="Knowledge" icon={<BookOpen aria-hidden />}>
        <Switch
          checked={config.kb_search_enabled}
          onCheckedChange={(kb_search_enabled) => set({ kb_search_enabled })}
          label="Search the flow's knowledge bases"
          description="Uses the knowledge bases attached in flow settings."
        />
      </Group>
      {catalogs && (
        <OverridesSection
          value={config.overrides}
          onChange={(overrides) => set({ overrides })}
          llm={catalogs.llm}
          voice={catalogs.voice}
          issues={issues}
        />
      )}
    </>
  );
}
