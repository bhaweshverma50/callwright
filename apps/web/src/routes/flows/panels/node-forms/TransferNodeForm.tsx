import type { TransferNodeConfig } from "../../../../api/flows";
import type { Errors } from "../../../agents/tools/forms/fieldRules";
import { TransferForm } from "../../../agents/tools/forms/TransferForm";
import { e164Error } from "./fieldRules";
import { issueFor, type FormProps } from "./shared";

/**
 * Transfer node (FR-017, T028): 005's transfer settings (fixed or model-chosen destination, cold
 * or warm with a briefing, hold message). A malformed number explains the international format
 * as soon as the field is left; the draft still saves.
 */
export function TransferNodeForm({ config, onChange, issues }: FormProps<TransferNodeConfig>) {
  const t = config.transfer;
  const errors: Errors = {};
  if (t.routing_type === "static" && t.number) {
    const e = e164Error(t.number);
    if (e) errors.number = e;
  } else if (t.routing_type === "static") {
    const e = issueFor(issues, "transfer.number");
    if (e) errors.number = e;
  }
  const routing = issueFor(issues, "transfer.routing_instructions");
  if (routing) errors.routing_instructions = routing;
  return (
    <div className="flex flex-col gap-5 px-5 py-5">
      <TransferForm config={t} errors={errors} onChange={(transfer) => onChange({ ...config, transfer })} />
    </div>
  );
}
