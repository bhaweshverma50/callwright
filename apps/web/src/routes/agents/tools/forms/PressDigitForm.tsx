import { Timer } from "lucide-react";
import type { PressDigitConfig } from "../../../../api/tools";
import { Field, Input } from "../../../../components";
import type { Errors } from "./fieldRules";
import { FormSection } from "./FormSection";

function NumberField({
  label,
  hint,
  value,
  error,
  max,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  error?: string;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <Input
          id={id}
          type="number"
          inputMode="numeric"
          min={0}
          max={max}
          step={100}
          suffix={<span className="font-mono text-[12px]">ms</span>}
          aria-describedby={describedBy}
          aria-invalid={invalid}
          value={Number.isFinite(value) ? value : ""}
          onChange={(e) => onChange(e.target.value === "" ? Number.NaN : Number(e.target.value))}
        />
      )}
    </Field>
  );
}

export function PressDigitForm({ config, errors, onChange }: { config: PressDigitConfig; errors: Errors; onChange: (c: PressDigitConfig) => void }) {
  return (
    <FormSection
      title="Timing"
      icon={<Timer aria-hidden />}
      description="Phone menus miss tones sent too early or too close together. A press that comes too soon waits for the cooldown; it is never dropped."
    >
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
        <NumberField
          label="Wait before pressing"
          hint="0 to 10,000 ms. Default 1,000."
          value={config.delay_ms}
          max={10000}
          error={errors.delay_ms}
          onChange={(v) => onChange({ ...config, delay_ms: v })}
        />
        <NumberField
          label="Cooldown between presses"
          hint="0 to 60,000 ms. Default 5,000."
          value={config.cooldown_ms}
          max={60000}
          error={errors.cooldown_ms}
          onChange={(v) => onChange({ ...config, cooldown_ms: v })}
        />
      </div>
    </FormSection>
  );
}
