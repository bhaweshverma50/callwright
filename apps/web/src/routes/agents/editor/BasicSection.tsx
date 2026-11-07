import { Bot, FileText, Globe, Hand, MessageSquareQuote, PenLine, Tag, UserRound } from "lucide-react";
import { useState } from "react";
import { Button, FieldRow, Input, Segmented, Select, Textarea, cn } from "../../../components";
import { CallerLanguageField } from "./CallerLanguageField";
import { syncVariables, type Catalogs } from "./catalogs";
import { FieldError, Note, Section, StackRow } from "./fields";
import { ModelPicker } from "./ModelPicker";
import { countWords } from "./surchargeRisk";
import { TemperatureControl } from "./TemperatureControl";
import type { AgentDraft } from "./useAgentDraft";
import { VariablesEditor } from "./VariablesEditor";
import { fieldId, fieldLabel } from "../config/fields";
import { schemaLimits } from "../../../lib/contract.gen";

const PROMPT_MAX = schemaLimits.AgentConfig.prompt.maxLength;
const GREETING_MAX = schemaLimits.AgentConfig.begin_message.maxLength;

/**
 * Basics tab: identity, model, prompt, greeting and variables (T040). Language changes reseed
 * speech recognition and the voice for the new language when the current ones cannot serve it.
 * Caller language switching (012) sits under the language.
 */
export function BasicSection({ draft, catalogs, onOpenAssistant }: { draft: AgentDraft; catalogs: Catalogs; onOpenAssistant: () => void }) {
  const { config } = draft;
  const [clamp, setClamp] = useState<string | null>(null);
  const [langNotice, setLangNotice] = useState<string | null>(null);
  const userFirst = config.start_speaker === "user";
  const promptLen = config.prompt.length;

  const changeLanguage = (code: string) => {
    const lang = catalogs.voice.languages.find((l) => l.code === code);
    if (!lang) return;
    const notes: string[] = [];
    draft.update((c) => {
      const prev = c.language;
      c.language = code;
      const stt = catalogs.voice.stt.find((p) => p.provider === c.stt.provider);
      const sttOk =
        stt &&
        (c.stt.model == null
          ? stt.models.some((m) => m.languages.includes(code))
          : stt.models.find((m) => m.id === c.stt.model)?.languages.includes(code));
      if (!sttOk) {
        c.stt = { provider: lang.stt_default.provider, model: lang.stt_default.model };
        notes.push(`speech recognition to ${catalogs.voice.stt.find((p) => p.provider === c.stt.provider)?.label ?? c.stt.provider} Auto`);
      }
      const tts = catalogs.voice.tts.find((p) => p.provider === c.tts.provider);
      const prevDefault = tts?.default_voice_by_language?.[prev];
      const nextDefault = tts?.default_voice_by_language?.[code];
      if (nextDefault && c.tts.voice_id === prevDefault && nextDefault !== prevDefault) {
        c.tts.voice_id = nextDefault;
        notes.push(`the voice to the ${tts?.label} default for ${lang.label}`);
      }
    });
    setLangNotice(notes.length ? `Switched ${notes.join(" and ")}.` : null);
    draft.touch("/language");
  };

  return (
    <div className="flex flex-col gap-5">
      <Section
        icon={<Tag />}
        title="Identity and model"
        description="What the agent is called, the language it speaks and the model that decides what it says."
      >
        <FieldRow icon={<Tag />} label={fieldLabel("/name")} htmlFor={fieldId("/name")} description="Shown in the agent list, calls and reports.">
          <Input
            id={fieldId("/name")}
            className="w-full"
            value={draft.name}
            maxLength={100}
            placeholder="For example, Front desk"
            aria-invalid={Boolean(draft.errorFor("/name"))}
            onChange={(e) => draft.setName(e.target.value)}
            onBlur={() => draft.touch("/name")}
          />
          <FieldError message={draft.errorFor("/name")} />
        </FieldRow>
        <FieldRow
          icon={<Globe />}
          label={fieldLabel("/language")}
          htmlFor={fieldId("/language")}
          description="The language callers speak. Speech recognition and voice defaults follow it."
        >
          <Select
            id={fieldId("/language")}
            className="w-full"
            value={config.language}
            onValueChange={changeLanguage}
            options={catalogs.voice.languages.map((l) => ({ value: l.code, label: l.label }))}
          />
          {langNotice && <Note tone="accent">{langNotice}</Note>}
          <FieldError message={draft.errorFor("/language")} />
        </FieldRow>
        <CallerLanguageField draft={draft} catalogs={catalogs} />
        <ModelPicker draft={draft} catalogs={catalogs} onClamp={setClamp} />
        <TemperatureControl draft={draft} catalogs={catalogs} clampNotice={clamp} />
      </Section>

      <Section icon={<FileText />} title="Prompt and greeting" description="How the agent behaves, and the first thing callers hear.">
        <StackRow
          icon={<FileText />}
          label={fieldLabel("/prompt")}
          htmlFor={fieldId("/prompt")}
          description="Instructions the agent follows on every call: its role, what to collect, what never to do."
          actions={
            <Button size="sm" variant="secondary" icon={<PenLine aria-hidden />} onClick={onOpenAssistant}>
              Write with AI
            </Button>
          }
        >
          <Textarea
            id={fieldId("/prompt")}
            className="min-h-[300px] resize-y text-[14px]"
            value={config.prompt}
            placeholder={"You are the front desk for {{company_name}}. You answer calls, book appointments and answer common questions..."}
            aria-invalid={Boolean(draft.errorFor("/prompt"))}
            aria-describedby="prompt-meta"
            onChange={(e) => {
              const v = e.target.value;
              draft.update((c) => {
                c.prompt = v;
                syncVariables(c);
              });
            }}
            onBlur={() => draft.touch("/prompt")}
          />
          <div id="prompt-meta" className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
            <FieldError message={draft.errorFor("/prompt")} />
            <span className={cn("ml-auto shrink-0 text-[12px] text-fg-3", promptLen > PROMPT_MAX && "text-danger-text")}>
              <span className="font-mono tnum">{countWords(config.prompt).toLocaleString()}</span> words,{" "}
              <span className="font-mono tnum">{promptLen.toLocaleString()}</span> of{" "}
              <span className="font-mono tnum">{PROMPT_MAX.toLocaleString()}</span> characters
            </span>
          </div>
        </StackRow>

        <FieldRow
          icon={<Hand />}
          label={fieldLabel("/start_speaker")}
          htmlFor={fieldId("/start_speaker")}
          description={userFirst ? "The agent waits for the caller to speak." : "The agent opens the call with the greeting."}
        >
          <Segmented
            id={fieldId("/start_speaker")}
            aria-label="Who speaks first"
            fill
            value={config.start_speaker}
            onValueChange={(v) => draft.update((c) => void (c.start_speaker = v))}
            options={[
              { value: "agent", label: "Agent", icon: <Bot aria-hidden /> },
              { value: "user", label: "Caller", icon: <UserRound aria-hidden /> },
            ]}
          />
        </FieldRow>

        <StackRow
          icon={<MessageSquareQuote />}
          label={fieldLabel("/begin_message")}
          htmlFor={fieldId("/begin_message")}
          description="The agent's first line. Variables work here too."
        >
          <Textarea
            id={fieldId("/begin_message")}
            className="min-h-[72px] resize-y"
            rows={2}
            disabled={userFirst}
            value={config.begin_message ?? ""}
            placeholder="Leave empty and the agent opens with a line it writes from the prompt."
            aria-invalid={Boolean(draft.errorFor("/begin_message"))}
            onChange={(e) => {
              const v = e.target.value;
              draft.update((c) => {
                c.begin_message = v;
                syncVariables(c);
              });
            }}
            onBlur={() => draft.touch("/begin_message")}
          />
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
            {userFirst ? (
              <Note>Not spoken while the caller speaks first. The text is kept for when you switch back.</Note>
            ) : !(config.begin_message ?? "").trim() ? (
              <Note>The agent writes its own opening line from the prompt.</Note>
            ) : (
              <FieldError message={draft.errorFor("/begin_message")} />
            )}
            <span className="ml-auto shrink-0 font-mono text-[12px] text-fg-3 tnum">
              {(config.begin_message ?? "").length}/{GREETING_MAX}
            </span>
          </div>
        </StackRow>

        <VariablesEditor draft={draft} />
      </Section>
    </div>
  );
}
