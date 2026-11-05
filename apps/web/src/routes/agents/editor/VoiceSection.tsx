import { AudioWaveform, Captions, Gauge, Mic2, Repeat2, Sparkle, Volume2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { useProviderVoices } from "../../../api/agents";
import { Button, FieldRow, Select, Skeleton } from "../../../components";
import { fieldId } from "../versions/versionLabels";
import { languageLabel, perMin, type Catalogs } from "./catalogs";
import { controlFor, FieldError, Note, Section, SliderRow } from "./fields";
import { NoiseCancellationSelect } from "./NoiseCancellationSelect";
import { SttPicker } from "./SttPicker";
import type { AgentDraft } from "./useAgentDraft";
import { usePreview } from "./usePreview";
import { PreviewButton, VoiceAvatar, VoiceTags } from "./VoiceAvatar";
import { VoicePickerDialog } from "./VoicePickerDialog";

/**
 * Voice and speech tab (T041, T095): speech recognition, noise cancellation, then the voice with
 * its provider, model, browser and tuning sliders. Switching provider applies that provider's
 * default model and its default voice for the agent's language, and says which voice it chose
 * (FR-010).
 */
export function VoiceSection({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const { tts, language } = draft.config;
  const provider = catalogs.voice.tts.find((p) => p.provider === tts.provider);
  const voices = useProviderVoices(tts.provider, {});
  const current = voices.data?.items.find((v) => v.voice_id === tts.voice_id);
  const [picker, setPicker] = useState(false);
  const [switched, setSwitched] = useState<{ provider: string; voice: string } | null>(null);
  const preview = usePreview();
  const controls = catalogs.voice.controls;
  const lang = languageLabel(catalogs.voice, language);
  const caps = provider?.capabilities ?? { speed: true, expressiveness: true, volume: true };
  const switchedName =
    switched && switched.provider === tts.provider ? (voices.data?.items.find((v) => v.voice_id === switched.voice)?.name ?? null) : null;

  return (
    <div className="flex flex-col gap-5">
      <Section icon={<Captions />} title="Speech recognition" description="How the agent hears the caller.">
        <SttPicker draft={draft} catalogs={catalogs} />
        <NoiseCancellationSelect draft={draft} catalogs={catalogs} />
      </Section>

      <Section icon={<Volume2 />} title="Voice" description="How the agent sounds. Play a sample before you choose.">
        <FieldRow
          icon={<Mic2 />}
          label="Voice provider"
          htmlFor={fieldId("/tts/provider")}
          description="Each provider has its own voices and models."
        >
          <Select
            id={fieldId("/tts/provider")}
            className="w-full"
            value={tts.provider}
            onValueChange={(p) => {
              const next = catalogs.voice.tts.find((x) => x.provider === p);
              if (!next) return;
              const voice = next.default_voice_by_language?.[language] ?? Object.values(next.default_voice_by_language ?? {})[0] ?? "";
              preview.stop();
              draft.update((c) => {
                c.tts.provider = p;
                c.tts.model = next.default_model;
                c.tts.voice_id = voice;
              });
              setSwitched({ provider: p, voice });
              draft.touch("/tts/provider");
            }}
            options={catalogs.voice.tts.map((p) => ({ value: p.provider, label: p.label }))}
          />
        </FieldRow>
        <FieldRow
          icon={<AudioWaveform />}
          label="Voice model"
          htmlFor={fieldId("/tts/model")}
          description="Trades speed of first audio against quality."
          hint="Each minute includes 750 characters of speech. Longer answers bill the voice for more minutes than the call lasted."
        >
          <Select
            id={fieldId("/tts/model")}
            className="w-full"
            value={tts.model}
            invalid={Boolean(draft.errorFor("/tts/model"))}
            onValueChange={(m) => {
              draft.update((c) => void (c.tts.model = m));
              draft.touch("/tts/model");
            }}
            options={(provider?.models ?? [])
              .filter((m) => !m.withdrawn || m.id === tts.model)
              .map((m) => ({ value: m.id, label: m.label, meta: perMin(m.price_per_min_usd) }))}
          />
          <FieldError message={draft.errorFor("/tts/model")} />
        </FieldRow>

        <div className="flex flex-col gap-3 px-5 py-4">
          <div
            id={fieldId("/tts/voice_id")}
            tabIndex={-1}
            className="flex flex-col gap-3 rounded-panel border border-line bg-surface-2/50 p-3.5 outline-none sm:flex-row sm:items-center"
          >
            {voices.isPending ? (
              <div className="flex flex-1 items-center gap-3">
                <Skeleton className="size-10 rounded-full" />
                <div className="flex flex-col gap-1.5">
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-3 w-56" />
                </div>
              </div>
            ) : (
              <div className="flex min-w-0 flex-1 items-center gap-3">
                {current ? <VoiceAvatar voice={current} /> : <VoiceAvatar voice={{ name: "?", voice_id: "none" }} />}
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="text-[12px] text-fg-3">Voice</span>
                  <span className="truncate text-[14px] font-semibold text-fg">
                    {current?.name ?? (tts.voice_id ? tts.voice_id : "No voice chosen")}
                  </span>
                  {current && <VoiceTags voice={current} languageLabel={(c) => languageLabel(catalogs.voice, c)} />}
                </div>
              </div>
            )}
            <div className="flex shrink-0 items-center gap-2">
              {current && (
                <PreviewButton
                  voice={current}
                  playing={preview.playing === current.voice_id}
                  onToggle={() => preview.toggle(current.voice_id, current.preview_url!)}
                />
              )}
              <Button icon={<Repeat2 aria-hidden />} onClick={() => setPicker(true)} disabled={!provider}>
                {tts.voice_id ? "Change voice" : "Choose a voice"}
              </Button>
            </div>
          </div>
          {current?.description && <p className="text-[13px] leading-relaxed text-fg-2">{current.description}</p>}
          <AnimatePresence>
            {switchedName && (
              <motion.div key={switched?.voice} initial={{ opacity: 0, y: -3 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Note tone="accent">
                  Voice set to {switchedName}, {provider?.label}'s default for {lang}.
                </Note>
              </motion.div>
            )}
          </AnimatePresence>
          <FieldError message={draft.errorFor("/tts/voice_id")} />
        </div>

        <SliderRow
          draft={draft}
          control={controlFor(controls, "/tts/speed")}
          pointer="/tts/speed"
          icon={<Gauge />}
          description="How fast the agent talks. 1.0x is the voice's natural pace."
          value={tts.speed}
          disabled={!caps.speed}
          disabledNote={`${provider?.label} does not support speed control.`}
          marks={[
            { value: 0.5, label: "0.5x" },
            { value: 1, label: "1x" },
            { value: 2, label: "2x" },
          ]}
          onChange={(v) => draft.update((c) => void (c.tts.speed = v))}
        />
        <SliderRow
          draft={draft}
          control={controlFor(controls, "/tts/expressiveness")}
          pointer="/tts/expressiveness"
          icon={<Sparkle />}
          description="Higher values vary pitch and emphasis more."
          hint="Sometimes called voice temperature. Around 0.9 sounds natural; very high values can sound theatrical on support calls."
          value={tts.expressiveness}
          disabled={!caps.expressiveness}
          disabledNote={`${provider?.label} does not support expressiveness.`}
          marks={[
            { value: 0, label: "Flat" },
            { value: 1, label: "Natural" },
            { value: 2, label: "Lively" },
          ]}
          onChange={(v) => draft.update((c) => void (c.tts.expressiveness = v))}
        />
        <SliderRow
          draft={draft}
          control={controlFor(controls, "/tts/volume")}
          pointer="/tts/volume"
          icon={<Volume2 />}
          description="Loudness of the agent's voice; 100% is normal."
          value={tts.volume}
          disabled={!caps.volume}
          disabledNote={`${provider?.label} does not support volume control.`}
          marks={[
            { value: 0, label: "0%" },
            { value: 1, label: "100%" },
            { value: 2, label: "200%" },
          ]}
          onChange={(v) => draft.update((c) => void (c.tts.volume = v))}
        />
      </Section>

      {provider && (
        <VoicePickerDialog
          open={picker}
          onOpenChange={setPicker}
          provider={provider}
          model={tts.model}
          language={language}
          catalog={catalogs.voice}
          value={tts.voice_id}
          onChoose={(v) => {
            draft.update((c) => void (c.tts.voice_id = v.voice_id));
            draft.touch("/tts/voice_id");
            setSwitched(null);
          }}
        />
      )}
    </div>
  );
}
