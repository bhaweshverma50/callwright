import { ChevronDown, KeyRound, PhoneIncoming } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { isApiError } from "../../../api/errors";
import { fieldErrors, problemMessage } from "../../../api/problems";
import { Button, Dialog, Field, Input, Segmented, Textarea, cn, focusRing } from "../../../components";
import { useImportNumber, type PhoneNumber, type Transport } from "../../../api/channels";
import { parseCidrs, stripScheme, terminationError } from "../validation";
import { AgentSelect } from "./shared";
import { E164_EXAMPLE, e164Error } from "../../../lib/e164";
import { useAllAgents } from "../../../api/agents";

type Errors = Partial<Record<"e164" | "label" | "termination_address" | "inbound_allowed_cidrs" | "form", string>>;

const TRANSPORTS: { value: Transport; label: string }[] = [
  { value: "auto", label: "Automatic" },
  { value: "udp", label: "UDP" },
  { value: "tcp", label: "TCP" },
  { value: "tls", label: "TLS" },
];

/**
 * Import a bring-your-own SIP number (010 T022, T081, FR-001, FR-002). Required fields are
 * checked on submit before anything is sent; the server's field errors land on the same fields.
 */
export function ImportNumberDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (n: PhoneNumber) => void;
}) {
  const save = useImportNumber();
  const agents = useAllAgents(open);
  const [e164, setE164] = useState("");
  const [label, setLabel] = useState("");
  const [address, setAddress] = useState("");
  const [transport, setTransport] = useState<Transport>("auto");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [cidrs, setCidrs] = useState("");
  const [agent, setAgent] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [errors, setErrors] = useState<Errors>({});

  useEffect(() => {
    if (!open) return;
    setE164("");
    setLabel("");
    setAddress("");
    setTransport("auto");
    setUsername("");
    setPassword("");
    setCidrs("");
    setAgent(null);
    setMore(false);
    setErrors({});
    save.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog opens
  }, [open]);

  const clear = (k: keyof Errors) => setErrors((e) => ({ ...e, [k]: undefined, form: undefined }));

  const submit = () => {
    const next: Errors = {};
    const numberErr = e164Error(e164);
    if (numberErr) next.e164 = numberErr;
    if (!label.trim()) next.label = "Enter a label.";
    const addressErr = terminationError(address);
    if (addressErr) next.termination_address = addressErr;
    const parsed = parseCidrs(cidrs);
    if (parsed.error) {
      next.inbound_allowed_cidrs = parsed.error;
      setMore(true);
    }
    setErrors(next);
    if (Object.keys(next).length) return;
    save.mutate(
      {
        e164: e164.trim(),
        label: label.trim(),
        termination_address: stripScheme(address),
        transport: /^sips:/i.test(address.trim()) && transport === "auto" ? "tls" : transport,
        ...(username.trim() && { auth_username: username.trim() }),
        ...(password && { auth_password: password }),
        ...(parsed.cidrs.length && { inbound_allowed_cidrs: parsed.cidrs }),
        ...(agent && { inbound_agent_id: agent }),
      },
      {
        onSuccess: (n) => {
          onImported(n);
          onOpenChange(false);
        },
        onError: (err) => {
          const fe = fieldErrors(err);
          const mapped: Errors = {
            e164: fe.e164,
            label: fe.label,
            termination_address: fe.termination_address,
            inbound_allowed_cidrs: fe.inbound_allowed_cidrs,
          };
          if (isApiError(err) && err.status === 409) {
            mapped.e164 =
              err.problem.code === "number_being_deleted"
                ? "This number is being deleted after its last call. Import it again once that finishes."
                : "This number is already connected to Callwright.";
          } else if (fe.inbound_agent_id) {
            mapped.form = fe.inbound_agent_id;
          } else if (!Object.values(mapped).some(Boolean)) {
            mapped.form = problemMessage(err, "phone number");
          }
          if (mapped.inbound_allowed_cidrs) setMore(true);
          setErrors(mapped);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !save.isPending && onOpenChange(o)}
      icon={<PhoneIncoming />}
      title="Import a phone number"
      description="Bring a number from your SIP trunk provider. Callwright sets up routing for it right away."
      size="md"
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={save.isPending}>
            Cancel
          </Button>
          <Button variant="primary" pending={save.isPending} onClick={submit}>
            Import number
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
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Phone number" hint={`E.164, for example ${E164_EXAMPLE}`} error={errors.e164}>
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                autoFocus
                inputMode="tel"
                className="font-mono"
                placeholder={E164_EXAMPLE}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={e164}
                onChange={(e) => {
                  setE164(e.target.value);
                  clear("e164");
                }}
              />
            )}
          </Field>
          <Field label="Label" error={errors.label}>
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                maxLength={100}
                placeholder="Main office line"
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={label}
                onChange={(e) => {
                  setLabel(e.target.value);
                  clear("label");
                }}
              />
            )}
          </Field>
        </div>
        <Field
          label="Termination address"
          hint="Where Callwright sends outbound calls: your provider's host or IP with an optional port. A sip: prefix is fine."
          error={errors.termination_address}
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              className="font-mono"
              placeholder="trunk.example-carrier.com:5060"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              value={address}
              onChange={(e) => {
                setAddress(e.target.value);
                clear("termination_address");
              }}
            />
          )}
        </Field>
        <div className="flex flex-col gap-1.5">
          <span id="transport-label" className="text-[13px] font-medium text-fg">
            Transport
          </span>
          <Segmented aria-labelledby="transport-label" value={transport} onValueChange={setTransport} options={TRANSPORTS} size="sm" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Carrier username" hint="Optional, for digest sign-in at your carrier.">
            {({ id, describedBy }) => (
              <Input
                id={id}
                autoComplete="off"
                maxLength={128}
                aria-describedby={describedBy}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            )}
          </Field>
          <Field label="Carrier password" hint="Stored encrypted and never shown again.">
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="password"
                autoComplete="new-password"
                maxLength={256}
                prefix={<KeyRound aria-hidden />}
                aria-describedby={describedBy}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>
        </div>
        <button
          type="button"
          aria-expanded={more}
          onClick={() => setMore((m) => !m)}
          className={cn("flex w-fit items-center gap-1.5 rounded-inline text-[13px] font-medium text-accent-text hover:underline", focusRing)}
        >
          <ChevronDown className={cn("size-4 transition-transform duration-200", more && "rotate-180")} aria-hidden />
          Agent and inbound security
        </button>
        <AnimatePresence initial={false}>
          {more && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="overflow-hidden"
            >
              <div className="flex flex-col gap-4 pb-1 pt-0.5">
                <Field label="Inbound agent" hint="Answers calls to this number. Without one, calls are declined before they cost anything.">
                  {({ id, describedBy }) => (
                    <AgentSelect
                      id={id}
                      describedBy={describedBy}
                      value={agent}
                      onValueChange={setAgent}
                      agents={agents.data}
                      noneLabel="No agent yet"
                    />
                  )}
                </Field>
                <Field
                  label="Allowed source addresses"
                  hint="Optional. Only accept inbound calls from these ranges, one per line (for example 203.0.113.0/24)."
                  error={errors.inbound_allowed_cidrs}
                >
                  {({ id, describedBy, invalid }) => (
                    <Textarea
                      id={id}
                      className="min-h-16 font-mono text-[13px]"
                      placeholder="203.0.113.0/24"
                      aria-describedby={describedBy}
                      aria-invalid={invalid}
                      value={cidrs}
                      onChange={(e) => {
                        setCidrs(e.target.value);
                        clear("inbound_allowed_cidrs");
                      }}
                    />
                  )}
                </Field>
              </div>
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
    </Dialog>
  );
}
