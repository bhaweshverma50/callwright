import { BookOpen, KeyRound, MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { isApiError } from "../../../api/errors";
import { fieldErrors, problemMessage } from "../../../api/problems";
import { Button, CopyButton, Dialog, Field, Input } from "../../../components";
import { useAgentOptions } from "../hooks/usePhoneNumbers";
import { useCreateWhatsApp, useWhatsAppSettings, type WhatsAppChannel } from "../hooks/useWhatsAppChannels";
import { E164_EXAMPLE, e164Error } from "../validation";
import { AgentSelect } from "./shared";

export const SETUP_GUIDE = "https://developers.facebook.com/docs/whatsapp/cloud-api/calling";

type Key = "meta_phone_number_id" | "e164" | "label" | "access_token" | "verify_token" | "app_secret" | "graph_api_version" | "form";
type Errors = Partial<Record<Key, string>>;

/** Checks shared with the server (data-model section 10). */
export function whatsappErrors(v: Record<string, string>): Errors {
  const e: Errors = {};
  if (!v.meta_phone_number_id?.trim()) e.meta_phone_number_id = "Enter the phone number ID from WhatsApp Manager.";
  else if (!/^\d{5,32}$/.test(v.meta_phone_number_id.trim())) e.meta_phone_number_id = "Digits only: the ID, not the phone number.";
  const n = e164Error(v.e164 ?? "", "business number");
  if (n) e.e164 = n;
  if (!v.label?.trim()) e.label = "Enter a label.";
  if (!v.access_token?.trim()) e.access_token = "Paste a permanent access token for the app.";
  const vt = v.verify_token ?? "";
  if (vt.length < 8 || vt.length > 128) e.verify_token = "8 to 128 characters. You paste the same value into the Meta app.";
  if (!v.app_secret?.trim()) e.app_secret = "Paste the app secret from the Meta app's basic settings.";
  if (v.graph_api_version && !/^v?\d+\.\d+$/.test(v.graph_api_version.trim())) e.graph_api_version = "A version like v23.0.";
  return e;
}

/**
 * Connect a WhatsApp Business number for voice (010 T056, T085, FR-021, FR-022): field rules
 * before sending, the callback address to copy, and WhatsApp's own reason when it refuses
 * (non-secret values are kept so only the token needs fixing).
 */
export function WhatsAppChannelDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onCreated: (c: WhatsAppChannel) => void;
}) {
  const settings = useWhatsAppSettings(open);
  const agents = useAgentOptions(open);
  const create = useCreateWhatsApp();
  const [v, setV] = useState<Record<string, string>>({});
  const [agent, setAgent] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});

  useEffect(() => {
    if (!open) return;
    setV({});
    setAgent(null);
    setErrors({});
    create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open]);

  useEffect(() => {
    if (open && settings.data && v.graph_api_version === undefined)
      setV((x) => ({ ...x, graph_api_version: settings.data.default_graph_api_version }));
  }, [open, settings.data, v.graph_api_version]);

  const set = (k: Key, value: string) => {
    setV((x) => ({ ...x, [k]: value }));
    setErrors((e) => ({ ...e, [k]: undefined, form: undefined }));
  };

  const submit = () => {
    const next = whatsappErrors(v);
    setErrors(next);
    if (Object.keys(next).length) return;
    create.mutate(
      {
        meta_phone_number_id: v.meta_phone_number_id!.trim(),
        e164: v.e164!.trim(),
        label: v.label!.trim(),
        access_token: v.access_token!.trim(),
        verify_token: v.verify_token!,
        app_secret: v.app_secret!.trim(),
        ...(v.graph_api_version?.trim() && { graph_api_version: v.graph_api_version.trim() }),
        ...(agent && { inbound_agent_id: agent }),
      },
      {
        onSuccess: (c) => {
          onCreated(c);
          onOpenChange(false);
        },
        onError: (err) => {
          const fe = fieldErrors(err);
          const out: Errors = {};
          for (const k of ["meta_phone_number_id", "e164", "label", "access_token", "verify_token", "app_secret", "graph_api_version"] as const) {
            if (fe[k]) out[k] = fe[k];
          }
          const code = isApiError(err) ? err.problem.code : undefined;
          if (code === "whatsapp_token_rejected") {
            out.access_token = err && isApiError(err) && err.problem.detail ? err.problem.detail : "WhatsApp rejected this token.";
            setV((x) => ({ ...x, access_token: "" }));
          } else if (code === "whatsapp_number_mismatch") {
            out.e164 = isApiError(err) ? err.problem.detail : "WhatsApp reports another number for this ID.";
          } else if (code === "whatsapp_number_already_connected") {
            out.meta_phone_number_id = "This WhatsApp number is already connected to Callwright.";
          } else if (code === "verify_token_in_use") {
            out.verify_token = "Another channel uses this verify token. Choose a different one.";
          } else if (code === "whatsapp_unreachable") {
            out.form = "WhatsApp could not be reached, so nothing was saved. Try again in a minute.";
          } else if (!Object.keys(out).length) {
            out.form = problemMessage(err, "WhatsApp channel");
          }
          setErrors(out);
        },
      },
    );
  };

  const input = (
    k: Key,
    label: string,
    props: { hint?: string; mono?: boolean; secret?: boolean; placeholder?: string; inputMode?: "numeric" | "tel" },
  ) => (
    <Field label={label} hint={props.hint} error={errors[k]}>
      {({ id, describedBy, invalid }) => (
        <Input
          id={id}
          type={props.secret ? "password" : "text"}
          autoComplete={props.secret ? "new-password" : "off"}
          inputMode={props.inputMode}
          className={props.mono ? "font-mono" : undefined}
          prefix={props.secret ? <KeyRound aria-hidden /> : undefined}
          placeholder={props.placeholder}
          aria-describedby={describedBy}
          aria-invalid={invalid}
          value={v[k] ?? ""}
          onChange={(e) => set(k, e.target.value)}
        />
      )}
    </Field>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !create.isPending && onOpenChange(o)}
      icon={<MessageCircle />}
      title="Connect WhatsApp voice"
      description="Let customers call your WhatsApp Business number and reach an agent."
      size="lg"
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={create.isPending}>
            Cancel
          </Button>
          <Button variant="primary" pending={create.isPending} onClick={submit}>
            Connect
          </Button>
        </>
      }
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <a
          href={SETUP_GUIDE}
          target="_blank"
          rel="noreferrer"
          className="flex w-fit items-center gap-1.5 text-[12.5px] font-medium text-accent-text hover:underline"
        >
          <BookOpen className="size-3.5" aria-hidden />
          WhatsApp Calling setup guide
        </a>
        <div className="grid gap-4 sm:grid-cols-2">
          {input("meta_phone_number_id", "Phone number ID", {
            hint: "In WhatsApp Manager, under the number's API settings.",
            mono: true,
            inputMode: "numeric",
            placeholder: "106540352242922",
          })}
          {input("e164", "Business phone number", {
            hint: `E.164, for example ${E164_EXAMPLE}`,
            mono: true,
            inputMode: "tel",
            placeholder: E164_EXAMPLE,
          })}
          {input("label", "Label", { placeholder: "Support WhatsApp" })}
          {input("graph_api_version", "API version", { hint: "Prefilled with the platform default.", mono: true, placeholder: "v23.0" })}
        </div>
        {input("access_token", "Access token", { hint: "A system user token with WhatsApp permissions. Stored encrypted.", secret: true })}
        <div className="grid gap-4 sm:grid-cols-2">
          {input("verify_token", "Verify token", { hint: "Any 8 to 128 characters; paste the same value in the Meta app.", secret: true })}
          {input("app_secret", "App secret", { hint: "Used to check that notifications come from Meta.", secret: true })}
        </div>
        <Field label="Callback URL" hint="Paste into the Meta app's webhook settings and subscribe to the calls field.">
          {({ id, describedBy }) => (
            <div className="flex items-center gap-2 rounded-control border border-line bg-surface-2/70 py-1 pl-3 pr-1">
              <code id={id} aria-describedby={describedBy} className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-fg">
                {settings.data?.callback_url ?? "Loading"}
              </code>
              {settings.data && <CopyButton value={settings.data.callback_url} label="Copy callback URL" />}
            </div>
          )}
        </Field>
        <Field label="Default agent" hint="Answers calls unless a caller route says otherwise. You can add it later.">
          {({ id, describedBy }) => (
            <AgentSelect id={id} describedBy={describedBy} value={agent} onValueChange={setAgent} agents={agents.data} noneLabel="No agent yet" />
          )}
        </Field>
        {errors.form && (
          <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-[13px] text-danger-text">
            {errors.form}
          </p>
        )}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
