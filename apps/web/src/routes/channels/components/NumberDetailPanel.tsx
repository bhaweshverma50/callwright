import { ArrowDownLeft, ArrowUpRight, KeyRound, Link2, PhoneOutgoing, RotateCw, Send, Shield, Trash2, Waypoints } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { isApiError } from "../../../api/errors";
import { fieldErrors, problemMessage } from "../../../api/problems";
import { Button, CopyButton, Drawer, Field, Input, Segmented, Textarea, Tooltip, cn, toast } from "../../../components";
import {
  useAgentOptions,
  useDeleteNumber,
  useRetryNumber,
  useSendTestEvent,
  useSipSettings,
  useUpdateNumber,
  type PhoneNumber,
  type PhoneNumberUpdate,
  type Transport,
} from "../hooks/usePhoneNumbers";
import { parseCidrs, stripScheme, terminationError, webhookUrlError } from "../validation";
import { DeleteNumberDialog } from "./DeleteNumberDialog";
import { OutboundCallDialog } from "./OutboundCallDialog";
import { ActiveCalls, AgentSelect, ChannelStatusBadge } from "./shared";

const TRANSPORTS: { value: Transport; label: string }[] = [
  { value: "auto", label: "Automatic" },
  { value: "udp", label: "UDP" },
  { value: "tcp", label: "TCP" },
  { value: "tls", label: "TLS" },
];

export function Section({
  icon,
  title,
  description,
  children,
  aside,
}: {
  icon: ReactNode;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="border-b border-line py-5 first:pt-1 last:border-0">
      <div className="mb-3.5 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-3.5">
            {icon}
          </span>
          <div className="flex flex-col gap-0.5">
            <h3 className="text-[14px] font-semibold text-fg">{title}</h3>
            {description && <p className="text-[12.5px] leading-relaxed text-fg-3">{description}</p>}
          </div>
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

interface Draft {
  label: string;
  termination: string;
  transport: Transport;
  username: string;
  password: string;
  removePassword: boolean;
  cidrs: string;
  webhook: string;
}

function draftOf(n: PhoneNumber): Draft {
  return {
    label: n.label,
    termination: n.termination_address,
    transport: n.transport ?? "auto",
    username: n.auth_username ?? "",
    password: "",
    removePassword: false,
    cidrs: (n.inbound_allowed_cidrs ?? []).join("\n"),
    webhook: n.inbound_webhook_url ?? "",
  };
}

/**
 * One number (010 T023, T035, T044, T064): status and retry, inbound and outbound agents (saved
 * on change), outbound call, editable routing with change tracking (an empty password keeps the
 * stored one), the inbound webhook with a test event, and deletion.
 */
export function NumberDetailPanel({ number, open, onOpenChange }: { number: PhoneNumber | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Drawer
      open={open && number !== null}
      onOpenChange={onOpenChange}
      title={number ? <span className="font-mono">{number.e164}</span> : ""}
      meta={number?.label}
      width="lg"
    >
      {number && <NumberDetail key={number.id} number={number} onClosed={() => onOpenChange(false)} />}
    </Drawer>
  );
}

function NumberDetail({ number, onClosed }: { number: PhoneNumber; onClosed: () => void }) {
  const agents = useAgentOptions();
  const sip = useSipSettings();
  const update = useUpdateNumber(number.id);
  const retry = useRetryNumber(number.id);
  const remove = useDeleteNumber(number.id);
  const test = useSendTestEvent();
  const [draft, setDraft] = useState<Draft>(() => draftOf(number));
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const [calling, setCalling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const base = useMemo(() => draftOf(number), [number]);
  const draining = number.status === "draining";
  const editable = !draining && number.status !== "provisioning";

  useEffect(() => setDraft(draftOf(number)), [number]);

  const dirty =
    draft.label !== base.label ||
    stripScheme(draft.termination) !== base.termination ||
    draft.transport !== base.transport ||
    draft.username !== base.username ||
    draft.password !== "" ||
    draft.removePassword ||
    draft.cidrs.trim() !== base.cidrs.trim() ||
    draft.webhook.trim() !== base.webhook;

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => ({ ...d, [k]: v }));
    setErrors((e) => ({ ...e, [k]: undefined, form: undefined }));
  };

  const patchAgent = (field: "inbound_agent_id" | "outbound_agent_id", value: string | null) =>
    update.mutate({ [field]: value } as PhoneNumberUpdate, {
      onSuccess: () =>
        toast({
          tone: "success",
          title: field === "inbound_agent_id" ? (value ? "Inbound agent attached" : "Inbound agent detached") : "Outbound agent saved",
          description:
            field === "inbound_agent_id" && !value
              ? "Calls to this number are now declined before they cost anything."
              : "Applies to new calls only.",
        }),
      onError: (err) => toast({ tone: "error", title: "Not saved", description: fieldErrors(err)[field] ?? problemMessage(err, "phone number") }),
    });

  const save = () => {
    const next: Record<string, string | undefined> = {};
    if (!draft.label.trim()) next.label = "Enter a label.";
    const t = terminationError(draft.termination);
    if (t) next.termination = t;
    const c = parseCidrs(draft.cidrs);
    if (c.error) next.cidrs = c.error;
    const w = webhookUrlError(draft.webhook);
    if (w) next.webhook = w;
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    const body: PhoneNumberUpdate = {};
    if (draft.label.trim() !== base.label) body.label = draft.label.trim();
    if (stripScheme(draft.termination) !== base.termination) body.termination_address = stripScheme(draft.termination);
    if (draft.transport !== base.transport) body.transport = draft.transport;
    if (draft.username !== base.username) body.auth_username = draft.username.trim() || null;
    if (draft.password) body.auth_password = draft.password;
    if (draft.removePassword && !draft.password) body.remove_auth_password = true;
    if (draft.cidrs.trim() !== base.cidrs.trim()) body.inbound_allowed_cidrs = c.cidrs;
    if (draft.webhook.trim() !== base.webhook) body.inbound_webhook_url = draft.webhook.trim() || null;
    update.mutate(body, {
      onSuccess: () => toast({ tone: "success", title: "Changes saved", description: "Calls already in progress keep their routing." }),
      onError: (err) => {
        const fe = fieldErrors(err);
        setErrors({
          label: fe.label,
          termination: fe.termination_address,
          cidrs: fe.inbound_allowed_cidrs,
          webhook: fe.inbound_webhook_url,
          form:
            isApiError(err) && err.problem.code === "routing_update_failed"
              ? "The routing service did not accept the change. Nothing was changed; try again."
              : Object.keys(fe).length
                ? undefined
                : problemMessage(err, "phone number"),
        });
      },
    });
  };

  const sendTest = () =>
    test.mutate(draft.webhook.trim(), {
      onSuccess: (a) =>
        toast({
          tone: a.status_code && a.status_code < 300 ? "success" : "error",
          title: a.status_code ? `Your endpoint answered ${a.status_code}` : "No answer from your endpoint",
          description: a.error ?? (a.duration_ms != null ? `In ${a.duration_ms} ms. Replies must arrive within 3 seconds.` : undefined),
        }),
      onError: (err) => toast({ tone: "error", title: "Test not sent", description: problemMessage(err, "webhook") }),
    });

  const telephonyOff = sip.data ? !sip.data.telephony_enabled : false;
  const callBlockedReason = number.status !== "active" ? "The number must be active." : telephonyOff ? "Telephony is not switched on yet." : null;

  return (
    <div className="flex flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-panel border border-line bg-surface-2/60 px-4 py-3">
        <ChannelStatusBadge status={number.status} />
        <ActiveCalls count={number.active_call_count} />
        <span className="ml-auto" />
        {number.status === "error" && (
          <Button
            size="sm"
            icon={<RotateCw aria-hidden />}
            pending={retry.isPending}
            onClick={() =>
              retry.mutate(undefined, {
                onSuccess: (n) =>
                  toast(
                    n.status === "active"
                      ? { tone: "success", title: "Routing is set up", description: "The number is active." }
                      : { tone: "error", title: "Setup failed again", description: n.status_detail ?? undefined },
                  ),
              })
            }
          >
            Retry setup
          </Button>
        )}
        {number.status_detail && <p className="basis-full text-[12.5px] leading-relaxed text-danger-text">{number.status_detail}</p>}
      </div>

      <Section icon={<Waypoints />} title="Agents" description="Changes apply to calls that start afterwards.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={
              <span className="flex items-center gap-1.5">
                <ArrowDownLeft className="size-3.5 text-fg-3" aria-hidden />
                Inbound
              </span>
            }
            hint="Answers calls to this number."
          >
            {({ id, describedBy }) => (
              <AgentSelect
                id={id}
                describedBy={describedBy}
                value={number.inbound_agent_id}
                agents={agents.data}
                noneLabel="No agent: decline calls"
                disabled={!editable || update.isPending}
                onValueChange={(v) => patchAgent("inbound_agent_id", v)}
              />
            )}
          </Field>
          <Field
            label={
              <span className="flex items-center gap-1.5">
                <ArrowUpRight className="size-3.5 text-fg-3" aria-hidden />
                Outbound
              </span>
            }
            hint="Default agent for calls from this number."
          >
            {({ id, describedBy }) => (
              <AgentSelect
                id={id}
                describedBy={describedBy}
                value={number.outbound_agent_id}
                agents={agents.data}
                noneLabel="No default agent"
                disabled={!editable || update.isPending}
                onValueChange={(v) => patchAgent("outbound_agent_id", v)}
              />
            )}
          </Field>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Tooltip content={callBlockedReason ?? "Call a number with an agent"}>
            <span>
              <Button variant="primary" icon={<PhoneOutgoing aria-hidden />} disabled={!!callBlockedReason} onClick={() => setCalling(true)}>
                Make outbound call
              </Button>
            </span>
          </Tooltip>
          {callBlockedReason && <span className="text-[12.5px] text-fg-3">{callBlockedReason}</span>}
        </div>
      </Section>

      <Section icon={<Link2 />} title="Routing" description="How outbound calls reach your carrier, and who may send inbound calls.">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (dirty) save();
          }}
        >
          <Field label="Label" error={errors.label}>
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                maxLength={100}
                disabled={!editable}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={draft.label}
                onChange={(e) => set("label", e.target.value)}
              />
            )}
          </Field>
          <Field label="Termination address" error={errors.termination}>
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                className="font-mono"
                disabled={!editable}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={draft.termination}
                onChange={(e) => set("termination", e.target.value)}
              />
            )}
          </Field>
          <div className="flex flex-col gap-1.5">
            <span id={`tr-${number.id}`} className="text-[13px] font-medium text-fg">
              Transport
            </span>
            <Segmented
              aria-labelledby={`tr-${number.id}`}
              size="sm"
              value={draft.transport}
              onValueChange={(v) => set("transport", v)}
              options={TRANSPORTS}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Carrier username">
              {({ id }) => (
                <Input id={id} autoComplete="off" disabled={!editable} value={draft.username} onChange={(e) => set("username", e.target.value)} />
              )}
            </Field>
            <Field
              label="Carrier password"
              hint={
                number.has_auth_password
                  ? draft.removePassword
                    ? "Will be removed when you save."
                    : "Saved. Leave empty to keep it."
                  : "None saved."
              }
              aside={
                number.has_auth_password && !draft.password ? (
                  <button
                    type="button"
                    className="text-[12px] font-medium text-accent-text hover:underline"
                    onClick={() => set("removePassword", !draft.removePassword)}
                  >
                    {draft.removePassword ? "Keep" : "Remove"}
                  </button>
                ) : undefined
              }
            >
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="new-password"
                  disabled={!editable}
                  prefix={<KeyRound aria-hidden />}
                  placeholder={number.has_auth_password && !draft.removePassword ? "••••••••" : ""}
                  aria-describedby={describedBy}
                  value={draft.password}
                  onChange={(e) => set("password", e.target.value)}
                />
              )}
            </Field>
          </div>
          <Field
            label={
              <span className="flex items-center gap-1.5">
                <Shield className="size-3.5 text-fg-3" aria-hidden />
                Allowed source addresses
              </span>
            }
            hint="One range per line. Empty accepts calls from any address."
            error={errors.cidrs}
          >
            {({ id, describedBy, invalid }) => (
              <Textarea
                id={id}
                className="min-h-16 font-mono text-[12.5px]"
                disabled={!editable}
                placeholder="203.0.113.0/24"
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={draft.cidrs}
                onChange={(e) => set("cidrs", e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Inbound webhook"
            hint="Optional. Called before the agent answers with the caller's number; reply with variables, another agent, or decline."
            error={errors.webhook}
          >
            {({ id, describedBy, invalid }) => (
              <div className="flex gap-2">
                <Input
                  id={id}
                  className="min-w-0 flex-1"
                  disabled={!editable}
                  placeholder="https://crm.example.com/callwright"
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  value={draft.webhook}
                  onChange={(e) => set("webhook", e.target.value)}
                />
                <Button
                  type="button"
                  icon={<Send aria-hidden />}
                  disabled={!draft.webhook.trim() || !!webhookUrlError(draft.webhook)}
                  pending={test.isPending}
                  onClick={sendTest}
                >
                  Send test
                </Button>
              </div>
            )}
          </Field>
          {errors.form && (
            <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-[13px] text-danger-text">
              {errors.form}
            </p>
          )}
          <div className={cn("flex items-center justify-end gap-2 transition-opacity", dirty ? "opacity-100" : "opacity-60")}>
            {dirty && (
              <Button type="button" variant="ghost" onClick={() => setDraft(base)}>
                Discard
              </Button>
            )}
            <Button type="submit" variant={dirty ? "primary" : "secondary"} disabled={!dirty || !editable} pending={update.isPending}>
              Save changes
            </Button>
          </div>
        </form>
      </Section>

      {number.direct_uri && !telephonyOff && (
        <Section icon={<ArrowDownLeft />} title="Direct address" description="Dial this number straight into Callwright, bypassing the carrier.">
          <div className="flex items-center gap-2 rounded-control border border-line bg-surface-2/70 py-1 pl-3 pr-1">
            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-fg">{number.direct_uri}</code>
            <CopyButton value={number.direct_uri} label="Copy direct address" />
          </div>
        </Section>
      )}

      <Section icon={<Trash2 />} title="Delete number" description="Stops routing and removes the number. Past calls keep showing it.">
        <Button variant="danger" icon={<Trash2 aria-hidden />} disabled={draining} onClick={() => setDeleting(true)}>
          {draining ? "Deleting when idle" : "Delete number"}
        </Button>
      </Section>

      <OutboundCallDialog open={calling} onOpenChange={setCalling} number={number} />
      <DeleteNumberDialog
        open={deleting}
        onOpenChange={setDeleting}
        what="number"
        name={number.e164}
        activeCalls={number.active_call_count}
        pending={remove.isPending}
        onDelete={async (whenIdle) => {
          const outcome = await remove.mutateAsync(whenIdle);
          toast(
            outcome === "deleted"
              ? { tone: "success", title: "Number deleted" }
              : { tone: "info", title: "Deleting when idle", description: "New calls are refused; it is removed after the last call ends." },
          );
          if (outcome === "deleted") onClosed();
        }}
      />
    </div>
  );
}
