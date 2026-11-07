import { AudioLines, BookOpen, CircleDot, Clock4, Cpu, FileText, MessageSquareQuote, Settings2, ShieldCheck, UserRound, Wrench } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { StartConfig } from "../../../api/flows";
import { Badge, Drawer, FieldRow, Panel, PanelRows, Segmented, cn, focusRing } from "../../../components";
import { ExpandEditor } from "./node-forms/ExpandEditor";
import {
  AdvancedSection,
  type AgentDraft,
  CallBehaviorSection,
  type Catalogs,
  EDITOR_PANELS,
  ModelPicker,
  sectionKeys,
  TemperatureControl,
  VoiceSection,
} from "../../agents/config";

export const SECTIONS = ["model", "voice", "call-behavior", "functions", "advanced", "knowledge-base", "quality-checks"] as const;
export type SettingsSection = (typeof SECTIONS)[number];

const META: Record<SettingsSection, { label: string; icon: ReactNode; saves: "draft" | "now" | "later" }> = {
  model: { label: "Model", icon: <Cpu aria-hidden />, saves: "draft" },
  voice: { label: "Voice", icon: <AudioLines aria-hidden />, saves: "draft" },
  "call-behavior": { label: "Call behaviour", icon: <Clock4 aria-hidden />, saves: "draft" },
  functions: { label: "Functions", icon: <Wrench aria-hidden />, saves: "now" },
  advanced: { label: "Advanced", icon: <Settings2 aria-hidden />, saves: "draft" },
  "knowledge-base": { label: "Knowledge base", icon: <BookOpen aria-hidden />, saves: "now" },
  "quality-checks": { label: "Quality checks", icon: <ShieldCheck aria-hidden />, saves: "later" },
};

/** Top-level config keys each draft section edits, so a section can show it has unsaved changes. */
const DRAFT_KEYS: Partial<Record<SettingsSection, readonly string[]>> = {
  model: ["llm", "prompt", "language"],
  voice: sectionKeys("voice"),
  "call-behavior": sectionKeys("behaviour"),
  advanced: [...sectionKeys("advanced"), "dynamic_variables"],
};

/**
 * Flow-wide settings (FR-023, FR-050 to FR-052, T083, T111): the agent's own settings, reusing
 * the single-prompt editor's sections and the same ranges. Each section is deep-linked by
 * `?configure=<section>` and says how it saves: draft sections go with the builder's Save
 * (and mark unsaved changes); functions and knowledge attach shared records at once. "Who speaks
 * first" edits the Start node, so there is one source for it.
 */
export function GlobalSettingsDrawer({
  open,
  section,
  onSection,
  onClose,
  draft,
  catalogs,
  changedKeys,
  start,
  onStart,
}: {
  open: boolean;
  section: SettingsSection;
  onSection: (s: SettingsSection) => void;
  onClose: () => void;
  draft: AgentDraft;
  catalogs: Catalogs;
  changedKeys: Set<string>;
  start: StartConfig | null;
  onStart: (patch: Partial<StartConfig>) => void;
}) {
  const [clamp, setClamp] = useState<string | null>(null);
  const unsaved = (s: SettingsSection) => (DRAFT_KEYS[s] ?? []).some((k) => changedKeys.has(k));
  const meta = META[section];
  return (
    <Drawer
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Flow settings"
      width="xl"
      meta={
        <span className="flex items-center gap-1.5 text-[13px] text-fg-3">
          {meta.saves === "draft" ? (
            <>
              <CircleDot className={cn("size-3", unsaved(section) ? "text-warning" : "text-fg-3")} aria-hidden />
              {unsaved(section) ? "Unsaved: saved with the flow" : "Saved with the flow"}
            </>
          ) : meta.saves === "now" ? (
            "Changes here save at once"
          ) : (
            "Arrives with evaluations"
          )}
        </span>
      }
    >
      <div className="-mx-5 -my-4 flex min-h-full flex-col md:flex-row">
        <nav
          aria-label="Settings sections"
          className="flex shrink-0 gap-1 overflow-x-auto border-b border-line p-2 md:w-[200px] md:flex-col md:border-b-0 md:border-r md:p-3"
        >
          {SECTIONS.map((s) => (
            <button
              key={s}
              type="button"
              aria-current={s === section ? "page" : undefined}
              onClick={() => onSection(s)}
              className={cn(
                "flex shrink-0 cursor-pointer items-center gap-2.5 rounded-control px-3 py-2 text-left text-[13px] transition-colors [&_svg]:size-4",
                s === section ? "bg-accent-soft font-medium text-accent-text" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
                focusRing,
              )}
            >
              {META[s].icon}
              <span className="whitespace-nowrap">{META[s].label}</span>
              {unsaved(s) && <span className="ml-auto size-1.5 rounded-full bg-warning" aria-label="Unsaved changes" />}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1 p-4 md:p-6">
          {section === "model" && (
            <div className="flex flex-col gap-5">
              <Panel title="Model" icon={<Cpu />} bodyClassName="p-0">
                <PanelRows>
                  <ModelPicker draft={draft} catalogs={catalogs} onClamp={setClamp} />
                  <TemperatureControl draft={draft} catalogs={catalogs} clampNotice={clamp} />
                </PanelRows>
              </Panel>
              <Panel title="Persona prompt" icon={<FileText />} description="Added before the instructions of every Agent and Task step.">
                <ExpandEditor
                  id="flow-persona"
                  label="Persona prompt"
                  rows={8}
                  maxLength={32000}
                  value={draft.config.prompt}
                  onChange={(prompt) => draft.update((c) => void (c.prompt = prompt))}
                  placeholder="You are the friendly receptionist of Harbour Clinic."
                />
              </Panel>
              {start && (
                <Panel title="Who speaks first" icon={<UserRound />} description="The same setting as the Start step.">
                  <PanelRows>
                    <FieldRow label="First speaker" htmlFor="flow-speaker" icon={<MessageSquareQuote />} inline>
                      <Segmented
                        id="flow-speaker"
                        aria-label="Who speaks first"
                        value={start.start_speaker}
                        onValueChange={(start_speaker) => onStart({ start_speaker })}
                        options={[
                          { value: "agent", label: "Agent" },
                          { value: "user", label: "Caller" },
                        ]}
                      />
                    </FieldRow>
                  </PanelRows>
                </Panel>
              )}
            </div>
          )}
          {section === "voice" && <VoiceSection draft={draft} catalogs={catalogs} />}
          {section === "call-behavior" && <CallBehaviorSection draft={draft} catalogs={catalogs} />}
          {section === "advanced" && <AdvancedSection draft={draft} catalogs={catalogs} />}
          {(section === "functions" || section === "knowledge-base") &&
            EDITOR_PANELS.filter((p) => p.id === (section === "functions" ? "tools" : "knowledge")).map((p) => (
              <p.component key={p.id} agentId={draft.base.id} agentType="flow" config={draft.config} update={draft.update} />
            ))}
          {section === "quality-checks" && (
            <Panel title="Quality checks" icon={<ShieldCheck />}>
              <p className="text-[13px] leading-relaxed text-fg-2">
                Evaluators and post-call analysis variables arrive with call evaluations. When they do, they appear here and save at once.
              </p>
              <Badge className="mt-3">Coming with evaluations</Badge>
            </Panel>
          )}
        </div>
      </div>
    </Drawer>
  );
}
