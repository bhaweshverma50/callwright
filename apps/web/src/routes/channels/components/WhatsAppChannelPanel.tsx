import { Check, CircleDashed, KeyRound, ListChecks, RotateCw, Route, Send, Settings2, Trash2, Waypoints } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { isApiError } from "../../../api/errors";
import { fieldErrors, problemMessage } from "../../../api/problems";
import { Button, CopyButton, Drawer, Field, Input, cn, toast } from "../../../components";
import { useAgentOptions, useSendTestEvent } from "../hooks/usePhoneNumbers";
import {
  useDeleteWhatsApp,
  useRetryWhatsApp,
  useUpdateWhatsApp,
  useWhatsAppSettings,
  type WhatsAppChannel,
  type WhatsAppChannelUpdate,
} from "../hooks/useWhatsAppChannels";
import { webhookUrlError } from "../validation";
import { CallerRoutesTable } from "./CallerRoutesTable";
import { DeleteNumberDialog } from "./DeleteNumberDialog";
import { Section } from "./NumberDetailPanel";
import { ActiveCalls, AgentSelect, ChannelStatusBadge } from "./shared";
import { timeAgo } from "../../../lib/format";

function Step({ done, title, detail, index }: { done: boolean; title: string; detail: string; index: number }) {
  return (
    <motion.li
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.06, duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className="flex items-start gap-3"
    >
      <span
        className={cn(
          "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full [&_svg]:size-3.5",
          done ? "bg-accent text-white" : "border border-dashed border-line-strong bg-surface text-fg-3",
        )}
      >
        {done ? <Check strokeWidth={3} aria-hidden /> : <CircleDashed aria-hidden />}
      </span>
      <div className="flex min-w-0 flex-col">
        <span className={cn("text-[14px] font-medium", done ? "text-fg" : "text-fg-2")}>{title}</span>
        <span className="text-[13px] text-fg-3">{detail}</span>
      </div>
    </motion.li>
  );
}

/**
 * One WhatsApp channel (010 T056, T060, T064): setup checklist with the callback address, default
 * agent, caller routes, credentials (an empty token keeps the stored one) and deletion.
 */
export function WhatsAppChannelPanel({
  channel,
  open,
  onOpenChange,
}: {
  channel: WhatsAppChannel | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  return (
    <Drawer
      open={open && channel !== null}
      onOpenChange={onOpenChange}
      title={channel?.label ?? ""}
      meta={channel ? <span className="font-mono">{channel.e164}</span> : undefined}
      width="lg"
    >
      {channel && <ChannelDetail key={channel.id} channel={channel} onClosed={() => onOpenChange(false)} />}
    </Drawer>
  );
}

function ChannelDetail({ channel, onClosed }: { channel: WhatsAppChannel; onClosed: () => void }) {
  const settings = useWhatsAppSettings();
  const agents = useAgentOptions();
  const update = useUpdateWhatsApp(channel.id);
  const retry = useRetryWhatsApp(channel.id);
  const remove = useDeleteWhatsApp(channel.id);
  const test = useSendTestEvent();
  const [creds, setCreds] = useState({
    label: channel.label,
    access_token: "",
    verify_token: "",
    app_secret: "",
    graph_api_version: channel.graph_api_version,
  });
  const [webhook, setWebhook] = useState(channel.inbound_webhook_url ?? "");
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const [deleting, setDeleting] = useState(false);
  const draining = channel.status === "draining";
  const dirty =
    creds.label.trim() !== channel.label ||
    !!creds.access_token ||
    !!creds.verify_token ||
    !!creds.app_secret ||
    creds.graph_api_version.trim() !== channel.graph_api_version ||
    webhook.trim() !== (channel.inbound_webhook_url ?? "");

  const save = () => {
    const next: Record<string, string | undefined> = {};
    if (!creds.label.trim()) next.label = "Enter a label.";
    if (creds.verify_token && (creds.verify_token.length < 8 || creds.verify_token.length > 128)) next.verify_token = "8 to 128 characters.";
    if (!/^v?\d+\.\d+$/.test(creds.graph_api_version.trim())) next.graph_api_version = "A version like v23.0.";
    const w = webhookUrlError(webhook);
    if (w) next.webhook = w;
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    const body: WhatsAppChannelUpdate = {};
    if (creds.label.trim() !== channel.label) body.label = creds.label.trim();
    if (creds.access_token.trim()) body.access_token = creds.access_token.trim();
    if (creds.verify_token) body.verify_token = creds.verify_token;
    if (creds.app_secret.trim()) body.app_secret = creds.app_secret.trim();
    if (creds.graph_api_version.trim() !== channel.graph_api_version) body.graph_api_version = creds.graph_api_version.trim();
    if (webhook.trim() !== (channel.inbound_webhook_url ?? "")) body.inbound_webhook_url = webhook.trim() || null;
    update.mutate(body, {
      onSuccess: (c) => {
        setCreds({ label: c.label, access_token: "", verify_token: "", app_secret: "", graph_api_version: c.graph_api_version });
        toast({
          tone: "success",
          title: "Channel saved",
          description: body.verify_token ? "Paste the new verify token in the Meta app; WhatsApp verifies the callback again." : undefined,
        });
      },
      onError: (err) => {
        const fe = fieldErrors(err);
        const code = isApiError(err) ? err.problem.code : undefined;
        setErrors({
          label: fe.label,
          access_token: code === "whatsapp_token_rejected" ? (isApiError(err) ? err.problem.detail : undefined) : fe.access_token,
          verify_token: code === "verify_token_in_use" ? "Another channel uses this verify token." : fe.verify_token,
          webhook: fe.inbound_webhook_url,
          form:
            Object.keys(fe).length || code === "whatsapp_token_rejected" || code === "verify_token_in_use"
              ? undefined
              : problemMessage(err, "WhatsApp channel"),
        });
      },
    });
  };

  const secretInput = (key: "access_token" | "verify_token" | "app_secret", label: string, hint: string) => (
    <Field label={label} hint={hint} error={errors[key]}>
      {({ id, describedBy, invalid }) => (
        <Input
          id={id}
          type="password"
          autoComplete="new-password"
          prefix={<KeyRound aria-hidden />}
          disabled={draining}
          aria-describedby={describedBy}
          aria-invalid={invalid}
          placeholder="Leave empty to keep"
          value={creds[key]}
          onChange={(e) => {
            setCreds((c) => ({ ...c, [key]: e.target.value }));
            setErrors((x) => ({ ...x, [key]: undefined }));
          }}
        />
      )}
    </Field>
  );

  return (
    <div className="flex flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-panel border border-line bg-surface-2/60 px-4 py-3">
        <ChannelStatusBadge status={channel.status} />
        <ActiveCalls count={channel.active_call_count} />
        <span className="ml-auto" />
        {channel.status === "error" && (
          <Button
            size="sm"
            icon={<RotateCw aria-hidden />}
            pending={retry.isPending}
            onClick={() =>
              retry.mutate(undefined, {
                onSuccess: (c) =>
                  toast(
                    c.status === "error"
                      ? { tone: "error", title: "Setup failed again", description: c.status_detail ?? undefined }
                      : { tone: "success", title: "Setup finished", description: "Calling is on for this number." },
                  ),
              })
            }
          >
            Retry setup
          </Button>
        )}
        {channel.status_detail && <p className="basis-full text-[13px] leading-relaxed text-danger-text">{channel.status_detail}</p>}
      </div>

      <Section
        icon={<ListChecks />}
        title="Setup"
        description="Callwright checks the token, turns on calling and waits for WhatsApp to verify the callback."
      >
        <ol className="flex flex-col gap-3">
          <Step
            index={0}
            done={!!channel.credentials_verified_at}
            title="Credentials checked"
            detail={
              channel.credentials_verified_at
                ? `The token can read this number. ${timeAgo(channel.credentials_verified_at)}`
                : "Waiting for a token WhatsApp accepts."
            }
          />
          <Step
            index={1}
            done={!!channel.calling_enabled_at}
            title="Calling turned on"
            detail={channel.calling_enabled_at ? "WhatsApp sends calls for this number to Callwright." : "Turned on once the token is accepted."}
          />
          <Step
            index={2}
            done={!!channel.webhook_verified_at}
            title="Callback verified"
            detail={
              channel.webhook_verified_at
                ? `WhatsApp confirmed the callback ${timeAgo(channel.webhook_verified_at)}.`
                : "Paste the callback URL and verify token in the Meta app."
            }
          />
        </ol>
        <div className="mt-4 flex items-center gap-2 rounded-control border border-line bg-surface-2/70 py-1 pl-3 pr-1">
          <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg">{settings.data?.callback_url ?? "Loading"}</code>
          {settings.data && <CopyButton value={settings.data.callback_url} label="Copy callback URL" />}
        </div>
        {channel.last_webhook_at && <p className="mt-2 text-[12px] text-fg-3">Last notification from WhatsApp {timeAgo(channel.last_webhook_at)}.</p>}
      </Section>

      <Section icon={<Waypoints />} title="Default agent" description="Answers every caller without a route of their own.">
        <AgentSelect
          aria-label="Default agent"
          value={channel.inbound_agent_id}
          agents={agents.data}
          noneLabel="No default agent"
          disabled={draining || update.isPending}
          onValueChange={(v) =>
            update.mutate(
              { inbound_agent_id: v },
              {
                onSuccess: () =>
                  toast({ tone: "success", title: v ? "Default agent saved" : "Default agent removed", description: "Applies to new calls only." }),
                onError: (err) =>
                  toast({
                    tone: "error",
                    title: "Not saved",
                    description: fieldErrors(err).inbound_agent_id ?? problemMessage(err, "WhatsApp channel"),
                  }),
              },
            )
          }
        />
      </Section>

      <Section
        icon={<Route />}
        title="Caller routes"
        description="Send specific callers to a specific agent, for example VIP customers to a dedicated agent."
        aside={
          channel.caller_route_count ? (
            <span className="shrink-0 whitespace-nowrap font-mono text-[12px] text-fg-3 tnum">{channel.caller_route_count} / 1,000</span>
          ) : undefined
        }
      >
        <CallerRoutesTable channelId={channel.id} disabled={draining} />
      </Section>

      <Section
        icon={<Settings2 />}
        title="Credentials and webhook"
        description="Tokens and the app secret are stored encrypted and never shown again."
      >
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (dirty) save();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Label" error={errors.label}>
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  maxLength={100}
                  disabled={draining}
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  value={creds.label}
                  onChange={(e) => setCreds((c) => ({ ...c, label: e.target.value }))}
                />
              )}
            </Field>
            <Field label="API version" error={errors.graph_api_version}>
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  className="font-mono"
                  disabled={draining}
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  value={creds.graph_api_version}
                  onChange={(e) => setCreds((c) => ({ ...c, graph_api_version: e.target.value }))}
                />
              )}
            </Field>
          </div>
          {secretInput("access_token", "Access token", `Ends in ${channel.access_token_last4 ?? "****"}. A new one is checked with WhatsApp first.`)}
          <div className="grid gap-4 sm:grid-cols-2">
            {secretInput("verify_token", "Verify token", `Ends in ${channel.verify_token_last4 ?? "****"}.`)}
            {secretInput("app_secret", "App secret", "Saved.")}
          </div>
          <Field
            label="Inbound webhook"
            hint="Optional. Called before the agent answers; reply with variables, another agent, or decline."
            error={errors.webhook}
          >
            {({ id, describedBy, invalid }) => (
              <div className="flex gap-2">
                <Input
                  id={id}
                  className="min-w-0 flex-1"
                  disabled={draining}
                  placeholder="https://crm.example.com/callwright"
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  value={webhook}
                  onChange={(e) => {
                    setWebhook(e.target.value);
                    setErrors((x) => ({ ...x, webhook: undefined }));
                  }}
                />
                <Button
                  type="button"
                  icon={<Send aria-hidden />}
                  disabled={!webhook.trim() || !!webhookUrlError(webhook)}
                  pending={test.isPending}
                  onClick={() =>
                    test.mutate(webhook.trim(), {
                      onSuccess: (a) =>
                        toast({
                          tone: a.status_code && a.status_code < 300 ? "success" : "error",
                          title: a.status_code ? `Your endpoint answered ${a.status_code}` : "No answer from your endpoint",
                          description: a.error ?? undefined,
                        }),
                      onError: (err) => toast({ tone: "error", title: "Test not sent", description: problemMessage(err, "webhook") }),
                    })
                  }
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
          <div className="flex justify-end">
            <Button type="submit" variant={dirty ? "primary" : "secondary"} disabled={!dirty || draining} pending={update.isPending}>
              Save changes
            </Button>
          </div>
        </form>
      </Section>

      <Section icon={<Trash2 />} title="Disconnect" description="Turns off calling for this number in WhatsApp and removes its routing.">
        <Button variant="danger" icon={<Trash2 aria-hidden />} disabled={draining} onClick={() => setDeleting(true)}>
          {draining ? "Deleting when idle" : "Delete channel"}
        </Button>
      </Section>

      <DeleteNumberDialog
        open={deleting}
        onOpenChange={setDeleting}
        what="WhatsApp channel"
        name={channel.label}
        activeCalls={channel.active_call_count}
        pending={remove.isPending}
        onDelete={async (whenIdle) => {
          const outcome = await remove.mutateAsync(whenIdle);
          toast(outcome === "deleted" ? { tone: "success", title: "Channel deleted" } : { tone: "info", title: "Deleting when idle" });
          if (outcome === "deleted") onClosed();
        }}
      />
    </div>
  );
}
