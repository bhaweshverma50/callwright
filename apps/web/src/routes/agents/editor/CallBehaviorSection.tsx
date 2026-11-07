import { BellRing, Clock4, Hourglass, MessageCircleReply, PhoneOff, Zap } from "lucide-react";
import { FieldRow } from "../../../components";
import type { Catalogs } from "./catalogs";
import { controlFor, Section, SliderRow, UnitNumberInput } from "./fields";
import { formatMs, formatSeconds } from "./formatters";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId, fieldLabel } from "../config/fields";

const minutes = (s: number) => Math.round((s / 60) * 100) / 100;
const fromMinutes = (m: number) => Math.round(m * 60);
const seconds = (ms: number) => Math.round(ms / 100) / 10;
const fromSeconds = (s: number) => Math.round(s * 1000);

/**
 * Call behaviour tab (T042): silence timeout, maximum duration, ring time, interruption and
 * responsiveness. Ranges, steps and labels come from the catalog control table; typed values show
 * their exact reading underneath ("Calls end at 2 min 30 s").
 */
export function CallBehaviorSection({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const cb = draft.config.call_behavior;
  const controls = catalogs.voice.controls;
  return (
    <div className="flex flex-col gap-5">
      <Section icon={<Clock4 />} title="Timing" description="When calls connect and when they end on their own.">
        <SliderRow
          draft={draft}
          control={controlFor(controls, "/call_behavior/end_on_silence_s")}
          pointer="/call_behavior/end_on_silence_s"
          icon={<PhoneOff />}
          description="Hang up when nobody has spoken for this long."
          value={cb.end_on_silence_s}
          marks={[10, 60, 120, 180, 240, 300].map((v) => ({ value: v, label: v < 60 ? `${v} s` : `${v / 60} min` }))}
          onChange={(v) => draft.update((c) => void (c.call_behavior.end_on_silence_s = v))}
        />
        <FieldRow
          icon={<Hourglass />}
          label={fieldLabel("/call_behavior/max_duration_s")}
          htmlFor={fieldId("/call_behavior/max_duration_s")}
          description="Calls end at this length, between 0.5 and 60 minutes."
        >
          <UnitNumberInput
            draft={draft}
            pointer="/call_behavior/max_duration_s"
            stored={cb.max_duration_s}
            toDisplay={minutes}
            fromDisplay={fromMinutes}
            unit="min"
            step={0.5}
            helper={(s) => `Calls end at ${formatSeconds(s)}.`}
          />
        </FieldRow>
        <FieldRow
          icon={<BellRing />}
          label={fieldLabel("/call_behavior/ring_duration_ms")}
          htmlFor={fieldId("/call_behavior/ring_duration_ms")}
          description="How long an inbound call rings before the agent answers, up to 30 seconds."
        >
          <UnitNumberInput
            draft={draft}
            pointer="/call_behavior/ring_duration_ms"
            stored={cb.ring_duration_ms}
            toDisplay={seconds}
            fromDisplay={fromSeconds}
            unit="s"
            step={0.5}
            helper={(ms) => (ms === 0 ? "Answers on the first ring." : `Rings for ${formatMs(ms)} before the agent answers.`)}
          />
        </FieldRow>
      </Section>

      <Section icon={<MessageCircleReply />} title="Turn taking" description="How the agent shares the conversation with the caller.">
        <SliderRow
          draft={draft}
          control={controlFor(controls, "/call_behavior/interruption_sensitivity")}
          pointer="/call_behavior/interruption_sensitivity"
          icon={<MessageCircleReply />}
          description="Higher lets callers cut in more easily while the agent talks."
          hint="Low suits noisy lines where background sounds would stop the agent mid-sentence. High suits quiet lines and impatient callers."
          value={cb.interruption_sensitivity}
          marks={[
            { value: 0, label: "Low" },
            { value: 0.5, label: "Medium" },
            { value: 1, label: "High" },
          ]}
          onChange={(v) => draft.update((c) => void (c.call_behavior.interruption_sensitivity = v))}
        />
        <SliderRow
          draft={draft}
          control={controlFor(controls, "/call_behavior/responsiveness")}
          pointer="/call_behavior/responsiveness"
          icon={<Zap />}
          description="Higher answers sooner after the caller stops talking."
          hint="Faster replies feel snappy but can cut in on callers who pause mid-thought. Slower replies wait longer before deciding the caller has finished."
          value={cb.responsiveness}
          marks={[
            { value: 0, label: "Slow" },
            { value: 0.5, label: "Medium" },
            { value: 1, label: "Fast" },
          ]}
          onChange={(v) => draft.update((c) => void (c.call_behavior.responsiveness = v))}
        />
      </Section>
    </div>
  );
}
