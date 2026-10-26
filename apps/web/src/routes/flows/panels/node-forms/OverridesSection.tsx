import { AudioLines, Cpu, Languages } from "lucide-react";
import type { LlmCatalog, VoiceCatalog } from "../../../../api/agents";
import type { Overrides } from "../../../../api/flows";
import { Field, Input, Segmented, Select, Slider } from "../../../../components";
import { Group, issueFor } from "./shared";

const DEFAULT = "__default__";
const PRESETS = [
  { value: "0.2", label: "Precise" },
  { value: "0.7", label: "Balanced" },
  { value: "1", label: "Creative" },
];

/**
 * Node overrides (FR-009, FR-054, T081, T112): each with "Use agent default". Changing the voice
 * provider clears the voice and voice model; a model with a fixed temperature shows the value
 * with the control disabled; the language drives the node's speech recognition (Auto). Ranges
 * come from 002's shared controls table.
 */
export function OverridesSection({
  value,
  onChange,
  llm,
  voice,
  issues,
}: {
  value: Overrides;
  onChange: (next: Overrides) => void;
  llm: LlmCatalog;
  voice: VoiceCatalog;
  issues: Parameters<typeof issueFor>[0];
}) {
  const set = (patch: Partial<Overrides>) => onChange({ ...value, ...patch });
  const modelKey = value.llm ? `${value.llm.provider}/${value.llm.model}` : DEFAULT;
  const model = value.llm ? llm.providers.find((p) => p.id === value.llm!.provider)?.models.find((m) => m.id === value.llm!.model) : undefined;
  const rule = model?.temperature as { fixed?: number; min?: number; max?: number; step?: number } | undefined;
  const fixed = rule?.fixed;
  const speed = voice.controls.find((c) => c.path === "tts.speed");
  const tts = value.tts;
  return (
    <Group title="Overrides" description="Only for this step. Everything else follows the flow's settings.">
      <Field label="Model" error={issueFor(issues, "overrides.llm")}>
        {({ id }) => (
          <Select
            id={id}
            value={modelKey}
            onValueChange={(v) => {
              if (v === DEFAULT) return set({ llm: null });
              const [provider, ...rest] = v.split("/");
              set({ llm: { provider: provider!, model: rest.join("/"), temperature: null } });
            }}
            groups={[
              { label: "Default", options: [{ value: DEFAULT, label: "Use agent default" }] },
              ...llm.providers.map((p) => ({
                label: p.label,
                options: p.models.filter((m) => !m.withdrawn).map((m) => ({ value: `${p.id}/${m.id}`, label: m.label })),
              })),
            ]}
          />
        )}
      </Field>
      {value.llm && (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
            <Cpu className="size-3.5 text-fg-3" aria-hidden /> Temperature
          </p>
          {fixed !== undefined ? (
            <p className="rounded-control bg-surface-2 px-3 py-2 text-[12.5px] text-fg-2">
              This model always runs at <span className="font-mono tnum">{fixed}</span>.
            </p>
          ) : (
            <Segmented
              fill
              size="sm"
              aria-label="Temperature"
              value={String(value.llm.temperature ?? rule?.min ?? 0.7)}
              onValueChange={(t) => set({ llm: { ...value.llm!, temperature: Number(t) } })}
              options={PRESETS}
            />
          )}
        </div>
      )}
      <Field label="Voice provider" error={issueFor(issues, "overrides.tts")}>
        {({ id }) => (
          <Select
            id={id}
            value={tts?.provider ?? DEFAULT}
            onValueChange={(v) =>
              v === DEFAULT
                ? set({ tts: null })
                : set({ tts: v === tts?.provider ? tts : { provider: v, model: null, voice_id: "", speed: tts?.speed ?? null, volume: null } })
            }
            options={[{ value: DEFAULT, label: "Use agent default" }, ...voice.tts.map((p) => ({ value: p.provider, label: p.label }))]}
          />
        )}
      </Field>
      {tts && (
        <>
          <Field
            label="Voice ID"
            hint="Changing the provider clears the voice; pick one for this provider."
            error={issueFor(issues, "overrides.tts.voice_id")}
          >
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                className="font-mono"
                value={tts.voice_id}
                onChange={(e) => set({ tts: { ...tts, voice_id: e.target.value } })}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
              />
            )}
          </Field>
          {speed && (
            <div className="flex flex-col gap-2">
              <p className="flex items-center justify-between text-[13px] font-medium text-fg">
                Speed <span className="font-mono text-[12px] text-fg-3 tnum">{(tts.speed ?? 1).toFixed(1)}x</span>
              </p>
              <Slider
                aria-label="Speed"
                value={tts.speed ?? 1}
                min={speed.min}
                max={speed.max}
                step={speed.step}
                onValueChange={(v) => set({ tts: { ...tts, speed: v } })}
                valueText={(v) => `${v.toFixed(1)}x`}
              />
            </div>
          )}
        </>
      )}
      <Field label="Language" hint="Speech recognition follows it (Auto)." error={issueFor(issues, "overrides.language")}>
        {({ id, describedBy }) => (
          <Select
            id={id}
            describedBy={describedBy}
            value={value.language ?? DEFAULT}
            onValueChange={(v) => set({ language: v === DEFAULT ? null : v, stt: v === DEFAULT ? value.stt : null })}
            options={[
              { value: DEFAULT, label: "Use agent default" },
              ...voice.languages.filter((l) => l.code !== "multi").map((l) => ({ value: l.code, label: l.label })),
            ]}
          />
        )}
      </Field>
      <span className="sr-only">
        <AudioLines aria-hidden />
        <Languages aria-hidden />
      </span>
    </Group>
  );
}
