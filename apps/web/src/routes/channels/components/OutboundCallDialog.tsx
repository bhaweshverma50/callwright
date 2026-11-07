import { CalendarClock, CircleCheck, Globe2, PhoneOutgoing, ShieldBan } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useAgent } from "../../../api/agents";
import { isApiError } from "../../../api/errors";
import { fieldErrors, problemMessage } from "../../../api/problems";
import { Button, CopyButton, Dialog, Field, Input, cn } from "../../../components";
import { usePlaceCall, type OutboundCallAccepted } from "../hooks/useOutboundCompliance";
import { useAgentOptions, type PhoneNumber } from "../hooks/usePhoneNumbers";
import { AgentSelect } from "./shared";
import { E164_EXAMPLE, e164Error } from "../../../lib/e164";

interface Block {
  reason: "dnc_listed" | "outside_calling_hours";
  zones: string[];
  local: string | null;
  next: string | null;
  source: string | null;
}

const ZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Australia/Sydney",
];

function newKey() {
  return `ui-${crypto.randomUUID()}`;
}

function formatLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(`${iso}Z`);
  return d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

function formatNext(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/**
 * Place an outbound call from a number (010 T034, T079, FR-020): destination, agent, the agent's
 * variables pre-filled with their defaults, an optional recipient timezone. Shows the call id, or
 * the reason it was blocked (do-not-call list, calling hours with local and next allowed time).
 */
export function OutboundCallDialog({ open, onOpenChange, number }: { open: boolean; onOpenChange: (o: boolean) => void; number: PhoneNumber }) {
  const place = usePlaceCall();
  const agents = useAgentOptions(open);
  const [to, setTo] = useState("");
  const [agentId, setAgentId] = useState<string | null>(number.outbound_agent_id ?? null);
  const [vars, setVars] = useState<Record<string, string>>({});
  const [timezone, setTimezone] = useState("");
  const [key, setKey] = useState(newKey);
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const [result, setResult] = useState<OutboundCallAccepted | null>(null);
  const [block, setBlock] = useState<Block | null>(null);
  const agent = useAgent(agentId ?? undefined);
  const variables = useMemo(() => agent.data?.draft_config.dynamic_variables ?? [], [agent.data]);

  useEffect(() => {
    if (!open) return;
    setTo("");
    setAgentId(number.outbound_agent_id ?? null);
    setTimezone("");
    setErrors({});
    setResult(null);
    setBlock(null);
    setKey(newKey());
    place.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open, number.id]);

  useEffect(() => {
    setVars(Object.fromEntries(variables.map((v) => [v.name, v.default ?? ""])));
  }, [variables]);

  const submit = () => {
    const next: Record<string, string | undefined> = {};
    const toErr = e164Error(to, "destination number");
    if (toErr) next.to_number = toErr;
    else if (to.trim() === number.e164) next.to_number = "Call a different number from the one you call from.";
    if (!agentId) next.agent_id = "Choose the agent that talks on this call.";
    setErrors(next);
    setBlock(null);
    if (Object.values(next).some(Boolean)) return;
    const filled = Object.fromEntries(Object.entries(vars).filter(([, v]) => v.trim() !== ""));
    place.mutate(
      {
        key,
        body: {
          to_number: to.trim(),
          from_number: number.e164,
          agent_id: agentId!,
          ring_timeout_s: 30,
          ...(Object.keys(filled).length && { dynamic_variables: filled }),
          ...(timezone.trim() && { recipient_timezone: timezone.trim() }),
        },
      },
      {
        onSuccess: setResult,
        onError: (err) => {
          // A block is not stored against the key, but a new attempt deserves a new key anyway.
          setKey(newKey());
          if (isApiError(err) && err.problem.code === "outbound_policy") {
            const p = err.problem as unknown as Record<string, unknown>;
            setBlock({
              reason: p.reason as Block["reason"],
              zones: (p.recipient_timezones as string[] | undefined) ?? [],
              local: (p.recipient_local_time as string | null | undefined) ?? null,
              next: (p.next_allowed_at as string | null | undefined) ?? null,
              source: (p.timezone_source as string | null | undefined) ?? null,
            });
            return;
          }
          const fe = fieldErrors(err);
          if (isApiError(err) && err.problem.code === "invalid_timezone")
            fe.recipient_timezone = "Not a timezone name, for example America/New_York.";
          setErrors({
            to_number: fe.to_number,
            recipient_timezone: fe.recipient_timezone,
            agent_id: fe.agent_id,
            form: Object.keys(fe).length ? undefined : isApiError(err) && err.problem.detail ? err.problem.detail : problemMessage(err, "call"),
          });
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !place.isPending && onOpenChange(o)}
      icon={<PhoneOutgoing />}
      title={result ? "Call started" : "Make an outbound call"}
      description={
        result ? undefined : (
          <>
            From <span className="font-mono text-fg">{number.e164}</span> ({number.label})
          </>
        )
      }
      footer={
        result ? (
          <>
            <Button asChild>
              <Link to="/calls">Open calls</Link>
            </Button>
            <Button variant="primary" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => onOpenChange(false)} disabled={place.isPending}>
              Cancel
            </Button>
            <Button variant="primary" icon={<PhoneOutgoing aria-hidden />} pending={place.isPending} onClick={submit}>
              Call now
            </Button>
          </>
        )
      }
    >
      {result ? (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col gap-3 rounded-panel border border-success/30 bg-success-soft/50 px-4 py-4"
        >
          <p className="flex items-center gap-2 text-[14px] font-medium text-fg">
            <CircleCheck className="size-4 text-success-text" aria-hidden />
            Dialling <span className="font-mono">{result.to_number}</span>
          </p>
          <div className="flex min-w-0 items-center gap-2 text-[13px] text-fg-2">
            <span className="shrink-0 whitespace-nowrap">Call id</span>
            <code className="min-w-0 truncate font-mono text-fg" title={result.call_id}>
              {result.call_id}
            </code>
            <CopyButton value={result.call_id} label="Copy call id" />
          </div>
          <p className="text-[13px] text-fg-3">
            It rings for up to 30 seconds. Busy, unanswered and failed calls are not charged.
            {result.recipient_timezones?.length ? ` Recipient time zone: ${result.recipient_timezones.join(", ")}.` : ""}
          </p>
        </motion.div>
      ) : (
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field label="Call this number" hint={`E.164, for example ${E164_EXAMPLE}`} error={errors.to_number}>
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                autoFocus
                inputMode="tel"
                className="font-mono"
                placeholder={E164_EXAMPLE}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={to}
                onChange={(e) => {
                  setTo(e.target.value);
                  setErrors((x) => ({ ...x, to_number: undefined }));
                  setBlock(null);
                }}
              />
            )}
          </Field>
          <Field label="Agent" error={errors.agent_id}>
            {({ id, describedBy, invalid }) => (
              <AgentSelect
                id={id}
                describedBy={describedBy}
                invalid={invalid}
                value={agentId}
                onValueChange={(v) => {
                  setAgentId(v);
                  setErrors((x) => ({ ...x, agent_id: undefined }));
                }}
                agents={agents.data}
              />
            )}
          </Field>
          {variables.length > 0 && (
            <fieldset className="flex flex-col gap-3 rounded-panel border border-line bg-surface-2/50 p-3.5">
              <legend className="px-1 text-[13px] font-medium text-fg-2">Variables for this call</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                {variables.map((v) => (
                  <Field key={v.name} label={<span className="font-mono text-[13px]">{v.name}</span>} hint={v.description ?? undefined}>
                    {({ id, describedBy }) => (
                      <Input
                        id={id}
                        inputSize="sm"
                        aria-describedby={describedBy}
                        value={vars[v.name] ?? ""}
                        placeholder={v.default ?? ""}
                        onChange={(e) => setVars((x) => ({ ...x, [v.name]: e.target.value }))}
                      />
                    )}
                  </Field>
                ))}
              </div>
            </fieldset>
          )}
          <Field
            label="Recipient timezone"
            hint="Optional. Calling hours use the zone of the destination's country or area; set it when you know better."
            error={errors.recipient_timezone}
          >
            {({ id, describedBy, invalid }) => (
              <>
                <Input
                  id={id}
                  list="cw-timezones"
                  prefix={<Globe2 aria-hidden />}
                  placeholder="America/New_York"
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  value={timezone}
                  onChange={(e) => {
                    setTimezone(e.target.value);
                    setErrors((x) => ({ ...x, recipient_timezone: undefined }));
                  }}
                />
                <datalist id="cw-timezones">
                  {ZONES.map((z) => (
                    <option key={z} value={z} />
                  ))}
                </datalist>
              </>
            )}
          </Field>
          <AnimatePresence>
            {block && (
              <motion.div
                role="alert"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className={cn(
                  "flex items-start gap-3 rounded-panel border px-4 py-3 text-[13px] leading-relaxed",
                  block.reason === "dnc_listed" ? "border-danger/30 bg-danger-soft/60" : "border-warning/30 bg-warning-soft/60",
                )}
              >
                {block.reason === "dnc_listed" ? (
                  <ShieldBan className="mt-0.5 size-4 shrink-0 text-danger-text" aria-hidden />
                ) : (
                  <CalendarClock className="mt-0.5 size-4 shrink-0 text-warning-text" aria-hidden />
                )}
                {block.reason === "dnc_listed" ? (
                  <p className="text-fg-2">
                    <span className="font-medium text-fg">This number is on your do-not-call list.</span> Nothing was dialled or charged. Remove it in
                    the Compliance tab to call it.
                  </p>
                ) : block.source === "unknown" ? (
                  <p className="text-fg-2">
                    <span className="font-medium text-fg">No timezone is known for this number.</span> Enter the recipient's timezone to check it
                    against your calling hours.
                  </p>
                ) : (
                  <p className="text-fg-2">
                    <span className="font-medium text-fg">Outside your calling hours for the recipient.</span> It is {formatLocal(block.local)} in{" "}
                    {block.zones.slice(0, 2).join(", ")}
                    {block.zones.length > 2 ? ` and ${block.zones.length - 2} more zones` : ""}.
                    {block.next ? ` The next allowed time is ${formatNext(block.next)} (your time).` : " No day has calling hours set."}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
          {errors.form && (
            <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-[13px] text-danger-text">
              {errors.form}
            </p>
          )}
          <button type="submit" hidden />
        </form>
      )}
    </Dialog>
  );
}
