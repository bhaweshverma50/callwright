import { Megaphone } from "lucide-react";
import type { SayConfig } from "../../../../api/flows";
import { Field, Switch } from "../../../../components";
import { ExpandEditor } from "./ExpandEditor";
import { Group, issueFor, type FormProps } from "./shared";
import { schemaLimits } from "../../../../lib/contract.gen";

/** Say node (FR-014): a fixed line, spoken without the model. */
export function SayForm({ config, onChange, issues }: FormProps<SayConfig>) {
  const set = (patch: Partial<SayConfig>) => onChange({ ...config, ...patch });
  const error = issueFor(issues, "message") ?? (config.message.length > 1000 ? "Use at most 1,000 characters." : null);
  return (
    <Group title="Message" icon={<Megaphone aria-hidden />} description="Use {{name}} to say a variable. No model runs, so it plays at once.">
      <Field label="Message" hideLabel error={error} hint={`${config.message.length} / 1,000`}>
        {({ id, describedBy, invalid }) => (
          <ExpandEditor
            id={id}
            label="Message"
            value={config.message}
            onChange={(message) => set({ message })}
            describedBy={describedBy}
            invalid={invalid}
            maxLength={schemaLimits.SayConfig.message.maxLength}
            placeholder="Your appointment is booked for {{appointment_time}}."
          />
        )}
      </Field>
      <Switch
        checked={config.allow_interruptions}
        onCheckedChange={(allow_interruptions) => set({ allow_interruptions })}
        label="Caller can interrupt"
        description="Turn off for disclosures that must be heard in full."
      />
    </Group>
  );
}
