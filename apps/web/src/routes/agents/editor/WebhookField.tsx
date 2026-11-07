import { Link2, Timer } from "lucide-react";
import { FieldRow, Input } from "../../../components";
import { FieldError, UnitNumberInput } from "./fields";
import { formatMs } from "./formatters";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId, fieldLabel } from "../config/fields";

const seconds = (ms: number) => Math.round(ms / 100) / 10;
const fromSeconds = (s: number) => Math.round(s * 1000);

/** Webhook address and timeout (FR-013, US1.9). The address must be public https. */
export function WebhookField({ draft }: { draft: AgentDraft }) {
  const a = draft.config.advanced;
  const urlId = fieldId("/advanced/webhook_url");
  return (
    <>
      <FieldRow
        icon={<Link2 />}
        label={fieldLabel("/advanced/webhook_url")}
        htmlFor={urlId}
        description="Receives call started, call ended and analysis events. Optional."
        hint="Events are sent as signed JSON POST requests. Only public https addresses are accepted, never private or local networks."
      >
        <Input
          id={urlId}
          type="url"
          inputMode="url"
          className="w-full"
          placeholder="https://api.example.com/calls"
          value={a.webhook_url ?? ""}
          aria-invalid={Boolean(draft.errorFor("/advanced/webhook_url"))}
          onChange={(e) => {
            const v = e.target.value;
            draft.update((c) => void (c.advanced.webhook_url = v.trim() ? v : null));
          }}
          onBlur={() => draft.touch("/advanced/webhook_url")}
        />
        <FieldError message={draft.errorFor("/advanced/webhook_url")} />
      </FieldRow>
      <FieldRow
        icon={<Timer />}
        label={fieldLabel("/advanced/webhook_timeout_ms")}
        htmlFor={fieldId("/advanced/webhook_timeout_ms")}
        description="How long to wait for your server, 1 to 30 seconds."
      >
        <UnitNumberInput
          draft={draft}
          pointer="/advanced/webhook_timeout_ms"
          stored={a.webhook_timeout_ms}
          toDisplay={seconds}
          fromDisplay={fromSeconds}
          unit="s"
          step={0.5}
          helper={(ms) => `Gives up after ${formatMs(ms)}.`}
        />
      </FieldRow>
    </>
  );
}
