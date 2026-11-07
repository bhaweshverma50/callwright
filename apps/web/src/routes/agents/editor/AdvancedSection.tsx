import { Music4, BrainCircuit, CircleDot, Disc, Grid3x3, Hash, Hourglass, Mic, PhoneMissed, ScanSearch, Voicemail, Webhook } from "lucide-react";
import { useMe } from "../../../api/queries";
import { FieldRow, Input, Segmented, Select, SwitchControl, Textarea } from "../../../components";
import { BackgroundAudioField } from "./BackgroundAudioField";
import { perMin, type Catalogs } from "./catalogs";
import { controlFor, FieldError, Section, SliderRow, StackRow } from "./fields";
import { PronunciationEditor } from "./PronunciationEditor";
import type { AgentDraft } from "./useAgentDraft";
import { WebhookField } from "./WebhookField";
import type { RecordingMode } from "../../../api/agents";
import { fieldId, fieldLabel } from "../config/fields";

const KEYS = ["#", "*", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;
const SAME = "same";

/**
 * Advanced tab (T043, T088): webhook, voicemail, keypad input, background audio, pronunciation,
 * the post-call analysis model and call recording. Each group is its own card with the same
 * anatomy; switched-off groups collapse to their switch.
 */
export function AdvancedSection({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const a = draft.config.advanced;
  const vm = a.voicemail_detection;
  const dtmf = a.dtmf;
  const me = useMe();
  const wsRecords = me.data?.workspace.recording_default;
  const recording: RecordingMode = a.recording ?? "inherit";
  const vmMsgId = fieldId("/advanced/voicemail_detection/message");

  return (
    <div className="flex flex-col gap-5">
      <Section icon={<Webhook />} title="Webhook" description="Send call events to your own systems.">
        <WebhookField draft={draft} />
      </Section>

      <Section icon={<Voicemail />} title="Voicemail and keypad" description="What happens when a machine answers, and when callers press keys.">
        <FieldRow
          inline
          icon={<Voicemail />}
          label={fieldLabel("/advanced/voicemail_detection/enabled")}
          htmlFor={fieldId("/advanced/voicemail_detection/enabled")}
          description="Notice when an outbound call reaches a voicemail box."
        >
          <SwitchControl
            id={fieldId("/advanced/voicemail_detection/enabled")}
            checked={vm.enabled}
            onCheckedChange={(on) => draft.update((c) => void (c.advanced.voicemail_detection.enabled = on))}
          />
        </FieldRow>
        {vm.enabled && (
          <>
            <FieldRow
              icon={<PhoneMissed />}
              label={fieldLabel("/advanced/voicemail_detection/action")}
              htmlFor={fieldId("/advanced/voicemail_detection/action")}
            >
              <Segmented
                id={fieldId("/advanced/voicemail_detection/action")}
                aria-label="When voicemail answers"
                fill
                value={vm.action}
                onValueChange={(v) => draft.update((c) => void (c.advanced.voicemail_detection.action = v))}
                options={[
                  { value: "hang_up", label: "Hang up" },
                  { value: "leave_message", label: "Leave a message" },
                ]}
              />
            </FieldRow>
            {vm.action === "leave_message" && (
              <StackRow
                icon={<Mic />}
                label={fieldLabel("/advanced/voicemail_detection/message")}
                htmlFor={vmMsgId}
                description="Spoken once after the beep, then the call ends."
              >
                <Textarea
                  id={vmMsgId}
                  rows={3}
                  className="resize-y"
                  placeholder="Hi, this is {{company_name}} returning your call. Please call us back at..."
                  value={vm.message ?? ""}
                  aria-invalid={Boolean(draft.errorFor("/advanced/voicemail_detection/message"))}
                  onChange={(e) => {
                    const v = e.target.value;
                    draft.update((c) => void (c.advanced.voicemail_detection.message = v || null));
                  }}
                  onBlur={() => draft.touch("/advanced/voicemail_detection/message")}
                />
                <div className="flex items-start justify-between gap-4">
                  <FieldError message={draft.errorFor("/advanced/voicemail_detection/message")} />
                  <span className="ml-auto shrink-0 font-mono text-[12px] text-fg-3 tnum">{(vm.message ?? "").length}/500</span>
                </div>
              </StackRow>
            )}
          </>
        )}
        <FieldRow
          inline
          icon={<Grid3x3 />}
          label={fieldLabel("/advanced/dtmf/enabled")}
          htmlFor={fieldId("/advanced/dtmf/enabled")}
          description="Let callers type numbers, such as an account or order number."
        >
          <SwitchControl
            id={fieldId("/advanced/dtmf/enabled")}
            checked={dtmf.enabled}
            onCheckedChange={(on) => draft.update((c) => void (c.advanced.dtmf.enabled = on))}
          />
        </FieldRow>
        {dtmf.enabled && (
          <>
            <SliderRow
              draft={draft}
              control={controlFor(catalogs.voice.controls, "/advanced/dtmf/timeout_ms")}
              pointer="/advanced/dtmf/timeout_ms"
              icon={<Hourglass />}
              description="The agent responds after this long without a key press."
              value={dtmf.timeout_ms ?? 2500}
              marks={[1000, 2500, 5000, 7500, 10000].map((v) => ({ value: v, label: `${v / 1000} s` }))}
              onChange={(v) => draft.update((c) => void (c.advanced.dtmf.timeout_ms = v))}
            />
            <FieldRow
              icon={<Hash />}
              label={fieldLabel("/advanced/dtmf/termination_key")}
              htmlFor={fieldId("/advanced/dtmf/termination_key")}
              description="Pressing it sends what the caller typed straight away."
            >
              <Select
                id={fieldId("/advanced/dtmf/termination_key")}
                className="w-full"
                value={dtmf.termination_key ?? "none"}
                onValueChange={(v) =>
                  draft.update((c) => void (c.advanced.dtmf.termination_key = v === "none" ? null : (v as (typeof KEYS)[number])))
                }
                options={[...KEYS.map((k) => ({ value: k, label: k })), { value: "none", label: "No end key" }]}
              />
            </FieldRow>
            <FieldRow
              icon={<CircleDot />}
              label={fieldLabel("/advanced/dtmf/digits")}
              htmlFor={fieldId("/advanced/dtmf/digits")}
              description="The agent responds as soon as this many digits are entered."
            >
              <Input
                id={fieldId("/advanced/dtmf/digits")}
                type="number"
                min={1}
                max={99}
                className="w-full"
                value={dtmf.digits ?? 10}
                aria-invalid={Boolean(draft.errorFor("/advanced/dtmf/digits"))}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  draft.update((c) => void (c.advanced.dtmf.digits = Number.isFinite(n) ? n : 0));
                }}
                onBlur={() => draft.touch("/advanced/dtmf/digits")}
              />
              <FieldError message={draft.errorFor("/advanced/dtmf/digits")} />
            </FieldRow>
          </>
        )}
      </Section>

      <Section icon={<Music4 />} title="Background audio" description="Ambience that makes the agent sound like it is in a real place.">
        <BackgroundAudioField draft={draft} catalogs={catalogs} />
      </Section>

      <Section icon={<ScanSearch />} title="Pronunciation" description="Fix how the voice says names, brands and acronyms.">
        <PronunciationEditor draft={draft} />
      </Section>

      <Section icon={<Disc />} title="Recording and analysis" description="Whether calls are recorded, and which model reviews them afterwards.">
        <FieldRow
          icon={<Disc />}
          label={fieldLabel("/advanced/recording")}
          htmlFor={fieldId("/advanced/recording")}
          description={
            recording === "inherit"
              ? `Follows the workspace setting, which is ${wsRecords === undefined ? "loading" : wsRecords ? "on" : "off"}.`
              : recording === "on"
                ? "Every call on this agent is recorded."
                : "Calls on this agent are never recorded."
          }
          hint="The workspace default lives in Settings. A change applies to calls that start after you save."
        >
          <Segmented
            id={fieldId("/advanced/recording")}
            aria-label="Call recording"
            fill
            value={recording}
            onValueChange={(v) => draft.update((c) => void (c.advanced.recording = v))}
            options={[
              { value: "inherit", label: "Workspace" },
              { value: "on", label: "Always" },
              { value: "off", label: "Never" },
            ]}
          />
        </FieldRow>
        <FieldRow
          icon={<BrainCircuit />}
          label={fieldLabel("/advanced/analysis_model")}
          htmlFor={fieldId("/advanced/analysis_model")}
          description="Reads the transcript after the call to fill in analysis results."
          hint="Post-call analysis is billed separately from the call, at the chosen model's rate."
        >
          <Select
            id={fieldId("/advanced/analysis_model")}
            className="w-full"
            value={a.analysis_model ? `${a.analysis_model.provider}/${a.analysis_model.model}` : SAME}
            onValueChange={(v) =>
              draft.update((c) => {
                if (v === SAME) c.advanced.analysis_model = null;
                else {
                  const [provider = "", model = ""] = v.split("/");
                  c.advanced.analysis_model = { provider, model };
                }
              })
            }
            groups={[
              { label: "", options: [{ value: SAME, label: "Same as the agent's model" }] },
              ...catalogs.llm.providers.map((p) => ({
                label: p.label,
                options: p.models
                  .filter((m) => !m.withdrawn)
                  .map((m) => ({ value: `${p.id}/${m.id}`, label: m.label, meta: perMin(m.price_per_min_usd) })),
              })),
            ]}
          />
          <FieldError message={draft.errorFor("/advanced/analysis_model")} />
        </FieldRow>
      </Section>
    </div>
  );
}
