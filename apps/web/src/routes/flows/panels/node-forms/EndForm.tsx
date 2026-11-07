import { PhoneOff, Tag } from "lucide-react";
import type { EndConfig } from "../../../../api/flows";
import { Field, Input } from "../../../../components";
import { ExpandEditor } from "./ExpandEditor";
import { reasonError } from "./fieldRules";
import { Group, issueFor, type FormProps } from "./shared";
import { schemaLimits } from "../../../../lib/contract.gen";

/** End node (FR-018): a closing line (or the agent's own goodbye), then hang up with a recorded reason. */
export function EndForm({ config, onChange, issues }: FormProps<EndConfig>) {
  const set = (patch: Partial<EndConfig>) => onChange({ ...config, ...patch });
  return (
    <>
      <Group
        title="Closing message"
        icon={<PhoneOff aria-hidden />}
        description="Leave empty to let the agent say goodbye in its own words, fitting the call (for example confirming a callback). Text you write here is spoken word for word before the call ends."
      >
        <Field label="Closing message" hideLabel error={issueFor(issues, "message")} hint={`${config.message.length} / 500`}>
          {({ id, describedBy, invalid }) => (
            <ExpandEditor
              id={id}
              label="Closing message"
              rows={3}
              maxLength={schemaLimits.EndConfig.message.maxLength}
              value={config.message}
              placeholder="Leave empty to let the agent say goodbye in its own words"
              onChange={(message) => set({ message })}
              describedBy={describedBy}
              invalid={invalid}
            />
          )}
        </Field>
      </Group>
      <Group title="End reason" icon={<Tag aria-hidden />} description="Stored on the call, so you can filter calls by how they ended.">
        <Field label="Reason" hideLabel error={issueFor(issues, "reason") ?? (config.reason ? reasonError(config.reason) : null)}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              value={config.reason}
              onChange={(e) => set({ reason: e.target.value })}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              className="font-mono"
            />
          )}
        </Field>
      </Group>
    </>
  );
}
