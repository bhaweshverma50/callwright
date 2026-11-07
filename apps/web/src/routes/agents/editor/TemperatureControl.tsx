import { Lock, Thermometer } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { FieldRow, Slider } from "../../../components";
import { isFixed, llmModel, type Catalogs } from "./catalogs";
import { formatDecimal, snap } from "./formatters";
import { FieldError, Note, ValuePill } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId, fieldLabel } from "../config/fields";

/**
 * Temperature (FR-007, US1.3). A fixed-temperature model shows its value on a locked slider with
 * the provider's reason; a ranged model uses its own min, max and step. A clamp after a model
 * switch is reported once, under the control.
 */
export function TemperatureControl({ draft, catalogs, clampNotice }: { draft: AgentDraft; catalogs: Catalogs; clampNotice: string | null }) {
  const { llm } = draft.config;
  const model = llmModel(catalogs.llm, llm.provider, llm.model);
  const rule = model?.temperature;
  const fixed = rule && isFixed(rule);
  const min = rule && !fixed ? rule.min : 0;
  const max = rule && !fixed ? rule.max : 2;
  const step = rule && !fixed ? rule.step : 0.1;
  const value = fixed ? rule.fixed : llm.temperature;
  const id = fieldId("/llm/temperature");
  return (
    <FieldRow
      icon={<Thermometer />}
      label={fieldLabel("/llm/temperature")}
      htmlFor={id}
      description="Lower is more predictable, higher is more varied."
    >
      <div className="flex w-full flex-col gap-1.5">
        <div className="flex items-center justify-end gap-2">
          {fixed && (
            <span className="inline-flex items-center gap-1 text-[12px] text-fg-3">
              <Lock className="size-3" aria-hidden /> Fixed
            </span>
          )}
          <ValuePill muted={fixed}>{formatDecimal(value)}</ValuePill>
        </div>
        <Slider
          id={id}
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={fixed}
          valueText={(v) => formatDecimal(v)}
          marks={[
            { value: min, label: "Precise" },
            { value: (min + max) / 2, label: "Balanced" },
            { value: max, label: "Creative" },
          ]}
          onValueChange={(v) => draft.update((c) => void (c.llm.temperature = snap(v, min, step)))}
          onValueCommit={() => draft.touch("/llm/temperature")}
        />
        {fixed && <Note>{rule.reason}.</Note>}
        <AnimatePresence>
          {clampNotice && (
            <motion.div initial={{ opacity: 0, y: -3 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="w-full">
              <Note tone="accent">{clampNotice}</Note>
            </motion.div>
          )}
        </AnimatePresence>
        <FieldError message={draft.errorFor("/llm/temperature")} />
      </div>
    </FieldRow>
  );
}
