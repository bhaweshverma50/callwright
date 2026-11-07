import * as RP from "@radix-ui/react-popover";
import { Check, Languages, ListChecks, Search, TriangleAlert, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import type { Language } from "../../../api/agents";
import { Button, FieldRow, Input, SwitchControl, cn, focusRing } from "../../../components";
import { languageSwitchingOf, onePerBase, switchTargets } from "../../../lib/callerLanguages";
import type { Catalogs } from "./catalogs";
import { FieldError, Note, StackRow } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId, fieldLabel } from "../config/fields";

const ENABLED = "/advanced/language_switching/enabled";
const LANGUAGES = "/advanced/language_switching/languages";

/**
 * Caller language (spec 012), under the agent's language on Basics: a switch that lets callers
 * change the call's language, and an optional list that limits which languages they get. Only
 * languages the agent's speech recognition and voice both support are offered (lib/callerLanguages).
 */
export function CallerLanguageField({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const { config } = draft;
  const switching = languageSwitchingOf(config);
  const { language, stt, tts } = config;
  const targets = useMemo(
    () => switchTargets(catalogs.voice, { language, stt, tts }),
    // The rule reads only these fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [catalogs.voice, language, stt.provider, tts.provider, tts.model],
  );
  const offered = useMemo(() => onePerBase(targets), [targets]);
  const flow = config.type === "flow";

  const setLanguages = (codes: string[]) => {
    draft.update((c) => void (c.advanced.language_switching = { ...languageSwitchingOf(c), languages: codes }));
    draft.touch(LANGUAGES);
  };

  return (
    <>
      <FieldRow
        inline
        icon={<Languages />}
        label={fieldLabel(ENABLED)}
        htmlFor={fieldId(ENABLED)}
        description="The agent switches speech recognition, replies and voice when a caller speaks another language, and phone callers start their next call in it."
      >
        <SwitchControl
          id={fieldId(ENABLED)}
          checked={!flow && switching.enabled}
          disabled={flow}
          onCheckedChange={(on) => draft.update((c) => void (c.advanced.language_switching = { ...languageSwitchingOf(c), enabled: on }))}
        />
      </FieldRow>
      {flow ? (
        <div className="px-5 pb-4 sm:pl-12">
          <Note>Flow agents keep the language of each step, so callers cannot switch.</Note>
        </div>
      ) : (
        switching.enabled && (
          <LanguagesRow draft={draft} catalogs={catalogs} targets={targets} offered={offered} chosen={switching.languages} onChange={setLanguages} />
        )
      )}
    </>
  );
}

function LanguagesRow({
  draft,
  catalogs,
  targets,
  offered,
  chosen,
  onChange,
}: {
  draft: AgentDraft;
  catalogs: Catalogs;
  targets: Language[];
  offered: Language[];
  chosen: string[];
  onChange: (codes: string[]) => void;
}) {
  const supported = new Set(targets.map((l) => l.code));
  const label = (code: string) => catalogs.voice.languages.find((l) => l.code === code)?.label ?? code;
  const warnings = (draft.validation?.warnings ?? []).filter((w) => w.pointer === LANGUAGES);
  const none = targets.length === 0;
  const description = none
    ? "This agent's speech recognition and voice support no other language. A multilingual voice model on the Voice tab adds some."
    : chosen.length
      ? `Callers can switch to ${chosen.length === 1 ? "this language" : `these ${chosen.length} languages`} only.`
      : `Callers can switch to any of the ${offered.length} languages this agent's speech recognition and voice support.`;

  return (
    <StackRow
      icon={<ListChecks />}
      label={fieldLabel(LANGUAGES)}
      description={description}
      actions={!none && <LanguagePicker targets={targets} chosen={chosen} onChange={onChange} />}
    >
      <div id={fieldId(LANGUAGES)} tabIndex={-1} className="flex flex-col gap-2 outline-none">
        {chosen.length === 0 ? (
          !none && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-7 items-center gap-1.5 rounded-full border border-line bg-surface-2 px-3 text-[13px] font-medium text-fg-2">
                <Languages className="size-3.5 text-accent-text" aria-hidden />
                All supported languages
              </span>
              <span className="text-[12px] text-fg-3">
                <span className="font-mono tnum">{offered.length}</span> available
              </span>
            </div>
          )
        ) : (
          <ul className="flex flex-wrap gap-1.5" aria-label="Chosen caller languages">
            <AnimatePresence initial={false}>
              {chosen.map((code) => {
                const ok = supported.has(code);
                return (
                  <motion.li
                    key={code}
                    layout
                    initial={{ opacity: 0, scale: 0.92 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.92 }}
                    transition={{ duration: 0.16 }}
                    title={ok ? undefined : "Not supported by this agent's speech recognition and voice"}
                    className={cn(
                      "inline-flex h-7 max-w-full items-center gap-1 rounded-full border pl-3 pr-1 text-[13px]",
                      ok ? "border-accent/30 bg-accent-soft text-accent-text" : "border-warning/40 bg-warning-soft text-warning-text",
                    )}
                  >
                    {!ok && <TriangleAlert className="size-3.5 shrink-0" aria-label="Not supported" />}
                    <span className="truncate">{label(code)}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${label(code)}`}
                      onClick={() => onChange(chosen.filter((c) => c !== code))}
                      className={cn("grid size-5 shrink-0 cursor-pointer place-items-center rounded-full hover:bg-fg/10", focusRing)}
                    >
                      <X className="size-3" aria-hidden />
                    </button>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
        {warnings.map((w) => (
          <Note key={w.message} tone="warning">
            {w.message}
          </Note>
        ))}
        <FieldError message={draft.errorFor(LANGUAGES)} />
      </div>
    </StackRow>
  );
}

/** Checklist of the supported languages in a popover, with a filter for long lists. */
function LanguagePicker({ targets, chosen, onChange }: { targets: Language[]; chosen: string[]; onChange: (codes: string[]) => void }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = q ? targets.filter((l) => l.label.toLowerCase().includes(q) || l.code.toLowerCase().startsWith(q)) : targets;
  const toggle = (code: string) =>
    onChange(
      chosen.includes(code)
        ? chosen.filter((c) => c !== code)
        : // Keep catalog order so the chips read the same way as the list.
          targets.map((l) => l.code).filter((c) => c === code || chosen.includes(c)),
    );
  return (
    <RP.Root onOpenChange={(open) => !open && setQuery("")}>
      <RP.Trigger asChild>
        <Button size="sm" variant="secondary" icon={<ListChecks aria-hidden />}>
          {chosen.length ? "Edit languages" : "Choose languages"}
        </Button>
      </RP.Trigger>
      <RP.Portal>
        <RP.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          aria-label={fieldLabel(LANGUAGES)}
          className="z-50 flex max-h-[min(460px,var(--radix-popover-content-available-height))] w-[min(380px,calc(100vw-24px))] flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-pop data-[state=open]:animate-pop-in"
        >
          <div className="flex flex-col gap-2.5 border-b border-line px-4 pb-3 pt-3.5">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-[14px] font-semibold text-fg">Caller languages</h2>
              <span className="text-[12px] text-fg-3">
                <span className="font-mono tnum">{targets.length}</span> to choose from
              </span>
            </div>
            <Input
              inputSize="sm"
              aria-label="Filter languages"
              placeholder="Filter languages"
              prefix={<Search aria-hidden />}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5 overflow-y-auto p-1.5 sm:grid-cols-2" aria-label="Supported languages">
            {shown.map((l) => {
              const on = chosen.includes(l.code);
              return (
                <li key={l.code}>
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    onClick={() => toggle(l.code)}
                    className={cn(
                      "flex w-full cursor-pointer items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-[13px] transition-colors duration-150",
                      on ? "text-fg" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
                      focusRing,
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "grid size-4 shrink-0 place-items-center rounded-[5px] border transition-colors duration-150",
                        on ? "bg-accent border-transparent text-white" : "border-line-strong bg-surface",
                      )}
                    >
                      {on && <Check className="size-3" strokeWidth={3} />}
                    </span>
                    <span className="min-w-0 truncate">{l.label}</span>
                  </button>
                </li>
              );
            })}
            {shown.length === 0 && <li className="col-span-full px-2.5 py-3 text-[13px] text-fg-3">No supported language matches.</li>}
          </ul>
          <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5">
            <Button size="sm" variant="ghost" disabled={!chosen.length} onClick={() => onChange([])}>
              Offer all supported
            </Button>
            <RP.Close asChild>
              <Button size="sm" variant="primary">
                Done
              </Button>
            </RP.Close>
          </div>
        </RP.Content>
      </RP.Portal>
    </RP.Root>
  );
}
