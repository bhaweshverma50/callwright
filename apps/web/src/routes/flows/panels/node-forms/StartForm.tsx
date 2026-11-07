import { Mic, MessageSquareQuote, UserRound, Wand2 } from "lucide-react";
import type { StartConfig } from "../../../../api/flows";
import { Field, Segmented } from "../../../../components";
import { ExpandEditor } from "./ExpandEditor";
import { Group, issueFor, type FormProps } from "./shared";
import { schemaLimits } from "../../../../lib/contract.gen";

/**
 * Start node (FR-019, FR-042, T107): who speaks first, then the greeting. When the caller speaks
 * first an optional short greeting plays before listening; a model-written greeting comes from
 * the first Agent or Task node's instructions.
 */
export function StartForm({ config, onChange, issues, nextLabel }: FormProps<StartConfig> & { nextLabel?: string | null }) {
  const set = (patch: Partial<StartConfig>) => onChange({ ...config, ...patch });
  const userFirst = config.start_speaker === "user";
  const generated = !userFirst && config.greeting_type === "generated";
  return (
    <>
      <Group title="Who speaks first" icon={<Mic aria-hidden />}>
        <Segmented
          fill
          aria-label="Who speaks first"
          value={config.start_speaker}
          onValueChange={(v) => set({ start_speaker: v })}
          options={[
            { value: "agent", label: "Agent", icon: <MessageSquareQuote aria-hidden /> },
            { value: "user", label: "Caller", icon: <UserRound aria-hidden /> },
          ]}
        />
        {!userFirst && (
          <Segmented
            fill
            size="sm"
            aria-label="Greeting"
            value={config.greeting_type}
            onValueChange={(v) => set({ greeting_type: v })}
            options={[
              { value: "static", label: "Fixed line" },
              { value: "generated", label: "Written by the model", icon: <Wand2 aria-hidden /> },
            ]}
          />
        )}
      </Group>
      <Group
        title={userFirst ? "Short greeting (optional)" : "Greeting"}
        description={
          userFirst
            ? "Played before the agent listens. Leave it empty for silence."
            : generated
              ? null
              : "Spoken at once when the call connects; the caller cannot talk over it."
        }
      >
        {generated ? (
          <p className="rounded-control bg-accent-soft/60 px-3 py-2.5 text-[13px] leading-relaxed text-accent-text">
            The opening line comes from {nextLabel ? <strong className="font-semibold">{nextLabel}</strong> : "the next step"}: its instructions write
            it. This needs Start to lead to an Agent or Task step.
          </p>
        ) : (
          <Field
            label="Greeting"
            hideLabel
            error={issueFor(issues, "greeting") ?? issueFor(issues, "greeting_type")}
            hint={`${config.greeting?.length ?? 0} / 500`}
          >
            {({ id, describedBy, invalid }) => (
              <ExpandEditor
                id={id}
                label="Greeting"
                rows={3}
                maxLength={schemaLimits.StartConfig.greeting.maxLength}
                value={config.greeting ?? ""}
                onChange={(greeting) => set({ greeting })}
                describedBy={describedBy}
                invalid={invalid}
                placeholder="Hi, thanks for calling. How can I help?"
              />
            )}
          </Field>
        )}
        {generated && issueFor(issues, "greeting_type") && <p className="text-[13px] text-danger-text">{issueFor(issues, "greeting_type")}</p>}
      </Group>
    </>
  );
}
