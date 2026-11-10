import { ArrowRightLeft, EarOff, Ear, Hash, ListChecks, Megaphone, Plus, Route, Shuffle, Snowflake, Flame, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { TransferConfig, WarmTransfer } from "../../../../api/tools";
import { Button, ChoiceGroup, Field, IconButton, Input, Segmented, Textarea } from "../../../../components";
import type { Errors } from "./fieldRules";
import { FormSection } from "./FormSection";
import { e164Error } from "../../../../lib/e164";
import { schemaLimits } from "../../../../lib/contract.gen";

const DEFAULT_WARM: WarmTransfer = { handoff_type: "private", briefing_message_type: "static", briefing_message: "" };

function AllowList({ numbers, errors, onChange }: { numbers: string[]; errors: Errors; onChange: (n: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const draftError = draft ? e164Error(draft.trim()) : null;
  const add = () => {
    const value = draft.trim();
    if (!value || draftError || numbers.includes(value)) return;
    onChange([...numbers, value]);
    setDraft("");
  };
  return (
    <Field
      label="Allowed numbers"
      error={errors.allowed_numbers}
      hint={draftError ?? "The agent can only transfer to these numbers."}
    >
      {({ id, describedBy }) => (
        <div className="flex flex-col gap-2.5">
          <div className="flex gap-2">
            <Input
              id={id}
              className="min-w-0 flex-1 font-mono"
              prefix={<Hash aria-hidden />}
              placeholder="+14155550100"
              aria-describedby={describedBy}
              aria-invalid={Boolean(draftError)}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add();
                }
              }}
            />
            <Button icon={<Plus aria-hidden />} disabled={!draft.trim() || Boolean(draftError)} onClick={add}>
              Add
            </Button>
          </div>
          {numbers.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="Allowed numbers">
              <AnimatePresence initial={false}>
                {numbers.map((n, i) => (
                  <motion.li
                    key={n}
                    layout
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    className={
                      errors[`allowed_numbers.${i}`]
                        ? "inline-flex h-7 items-center gap-1 rounded-full bg-danger-soft pl-2.5 pr-0.5 font-mono text-[12px] text-danger-text"
                        : "inline-flex h-7 items-center gap-1 rounded-full bg-surface-3 pl-2.5 pr-0.5 font-mono text-[12px] text-fg tnum"
                    }
                  >
                    {n}
                    <IconButton label={`Remove ${n}`} className="size-6 [&_svg]:size-3" onClick={() => onChange(numbers.filter((x) => x !== n))}>
                      <X aria-hidden />
                    </IconButton>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
        </div>
      )}
    </Field>
  );
}

export function TransferForm({ config, errors, onChange }: { config: TransferConfig; errors: Errors; onChange: (c: TransferConfig) => void }) {
  const set = (patch: Partial<TransferConfig>) => onChange({ ...config, ...patch });
  const warm = config.warm_transfer ?? DEFAULT_WARM;
  const setWarm = (patch: Partial<WarmTransfer>) => set({ warm_transfer: { ...warm, ...patch } });
  return (
    <>
      <FormSection
        title="Destination"
        icon={<Route aria-hidden />}
        description="Where the caller goes. Transfers work on phone calls; web calls answer that a transfer is not possible."
      >
        <Segmented
          className="w-fit self-start"
          aria-label="Routing"
          value={config.routing_type}
          onValueChange={(v) => set({ routing_type: v })}
          options={[
            { value: "static", label: "One number", icon: <Hash aria-hidden /> },
            { value: "dynamic", label: "Agent chooses", icon: <Shuffle aria-hidden /> },
          ]}
        />
        {config.routing_type === "static" ? (
          <Field label="Phone number" error={errors.number} hint="In +E.164 form.">
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                className="font-mono"
                prefix={<Hash aria-hidden />}
                placeholder="+14155550100"
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={config.number ?? ""}
                onChange={(e) => set({ number: e.target.value.trim() })}
              />
            )}
          </Field>
        ) : (
          <>
            <Field label="How to choose the number" error={errors.routing_instructions} hint="Added to the tool description the model reads.">
              {({ id, describedBy, invalid }) => (
                <Textarea
                  id={id}
                  maxLength={schemaLimits.TransferSpec.routing_instructions.maxLength}
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  placeholder="Billing questions go to +14155550100, appointment changes to +14155550111."
                  value={config.routing_instructions ?? ""}
                  onChange={(e) => set({ routing_instructions: e.target.value })}
                />
              )}
            </Field>
            <AllowList numbers={config.allowed_numbers} errors={errors} onChange={(allowed_numbers) => set({ allowed_numbers })} />
          </>
        )}
      </FormSection>

      <FormSection
        title="Handoff"
        icon={<ArrowRightLeft aria-hidden />}
        description="Cold hands the call over at once. Warm briefs the person before connecting."
      >
        <ChoiceGroup
          aria-label="Transfer type"
          size="sm"
          value={config.transfer_type}
          onValueChange={(v) => set({ transfer_type: v, warm_transfer: v === "warm" ? warm : null })}
          options={[
            { value: "cold", title: "Cold", icon: <Snowflake aria-hidden />, description: "The caller is put through straight away." },
            { value: "warm", title: "Warm", icon: <Flame aria-hidden />, description: "The agent briefs your colleague first." },
          ]}
        />
        <AnimatePresence initial={false}>
          {config.transfer_type === "warm" && (
            <motion.div
              key="warm"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="overflow-hidden"
            >
              <div className="flex flex-col gap-4 rounded-panel bg-surface-2/70 p-4">
                <ChoiceGroup
                  aria-label="Who hears the briefing"
                  size="sm"
                  value={warm.handoff_type}
                  onValueChange={(v) => setWarm({ handoff_type: v })}
                  options={[
                    { value: "private", title: "Private briefing", icon: <EarOff aria-hidden />, description: "Only your colleague hears it." },
                    { value: "public", title: "Briefing on the call", icon: <Ear aria-hidden />, description: "The caller hears it too." },
                  ]}
                />
                <Segmented
                  className="w-fit self-start"
                  aria-label="Briefing source"
                  size="sm"
                  value={warm.briefing_message_type}
                  onValueChange={(v) => setWarm({ briefing_message_type: v })}
                  options={[
                    { value: "static", label: "Fixed text", icon: <Megaphone aria-hidden /> },
                    { value: "prompt", label: "Written from the call", icon: <ListChecks aria-hidden /> },
                  ]}
                />
                <Field
                  label={warm.briefing_message_type === "prompt" ? "What the briefing covers" : "Briefing"}
                  error={errors.briefing_message}
                  hint={warm.briefing_message_type === "prompt" ? "The model writes one line from the call and these instructions." : undefined}
                >
                  {({ id, describedBy, invalid }) => (
                    <Textarea
                      id={id}
                      maxLength={1000}
                      className="min-h-20 bg-surface"
                      aria-describedby={describedBy}
                      aria-invalid={invalid}
                      placeholder={
                        warm.briefing_message_type === "prompt"
                          ? "Say who is calling and what they need, in one sentence."
                          : "I have a caller who would like to reschedule an appointment."
                      }
                      value={warm.briefing_message}
                      onChange={(e) => setWarm({ briefing_message: e.target.value })}
                    />
                  )}
                </Field>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-[minmax(0,1fr)_180px]">
          <Field label="Hold message" hint="Spoken to the caller while the transfer connects.">
            {({ id, describedBy }) => (
              <Input
                id={id}
                maxLength={schemaLimits.TransferSpec.hold_message.maxLength}
                aria-describedby={describedBy}
                value={config.hold_message}
                onChange={(e) => set({ hold_message: e.target.value })}
              />
            )}
          </Field>
          <Field label="Ring timeout" error={errors.ring_timeout_s} hint="5 to 120 s.">
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                type="number"
                min={5}
                max={120}
                suffix={<span className="font-mono text-[12px]">s</span>}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={Number.isFinite(config.ring_timeout_s) ? config.ring_timeout_s : ""}
                onChange={(e) => set({ ring_timeout_s: e.target.value === "" ? Number.NaN : Number(e.target.value) })}
              />
            )}
          </Field>
        </div>
      </FormSection>
    </>
  );
}
