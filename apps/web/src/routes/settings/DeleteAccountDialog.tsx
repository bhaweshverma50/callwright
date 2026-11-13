import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { scheduleAccountDeletion } from "../../api/account";
import { requestPasswordReset } from "../../api/auth";
import { isApiError } from "../../api/errors";
import { fieldErrors, problemMessage, problemText } from "../../api/problems";
import type { Me } from "../../api/types";
import { Button, Checkbox, Dialog, Field, FormAlert, Input, MoneyText, toast } from "../../components";
import { dateLabel } from "../../lib/format";
import { formatUsd } from "../../lib/money";
import { AUTH_PAGES } from "../../lib/paths";
import { PasswordField } from "./PasswordField";

/** Days between asking and the erase; the API's grace period (account/service.py GRACE). */
export const GRACE_DAYS = 30;

/** What is erased, in the words the dialog and the Settings area share. */
export const ERASED = [
  "Agents and all their versions",
  "Call history, transcripts and recordings",
  "Knowledge bases and their documents",
  "Datasets, simulations, test cases and issues",
  "Google connections, which are also revoked at Google",
] as const;

/** Whether every confirmation is in place: the exact workspace name, the forfeit box, the password or email. */
export function deletionReady(
  me: Pick<Me, "user" | "workspace">,
  typed: { name: string; forfeit: boolean; password: string; email: string },
): boolean {
  const proof = me.user.has_password ? typed.password.length > 0 : typed.email.trim().toLowerCase() === me.user.email.toLowerCase();
  return typed.name === me.workspace.name && typed.forfeit && proof;
}

/**
 * Delete the account. Nothing is erased for 30 days: the person is signed out everywhere and can
 * sign back in during that time to keep the account. The dialog states what goes, the exact
 * balance forfeited and the date, and the Delete button stays off until each confirmation is made.
 */
export function DeleteAccountDialog({ me, open, onOpenChange }: { me: Me; open: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [forfeit, setForfeit] = useState(false);
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const hasPassword = me.user.has_password;
  const eraseOn = dateLabel(new Date(Date.now() + GRACE_DAYS * 86_400_000).toISOString());
  const balance = formatUsd(me.balance_usd, { places: 3 });

  const del = useMutation({
    mutationFn: () => scheduleAccountDeletion({ confirmWorkspaceName: name, ...(hasPassword ? { password } : { confirmEmail: email.trim() }) }),
    onSuccess: (scheduled) => {
      // The server already ended every session. The sign-in page drops this device's tokens (a
      // route guard that saw them go would send the person to sign in without the notice).
      navigate(`${AUTH_PAGES.login}?deletion=${encodeURIComponent(scheduled.scheduled_at)}`, { replace: true });
    },
  });

  function close(value: boolean) {
    if (!value) {
      setName("");
      setForfeit(false);
      setPassword("");
      setEmail("");
      del.reset();
    }
    onOpenChange(value);
  }

  const sendLink = useMutation({
    mutationFn: () => requestPasswordReset(me.user.email),
    onSuccess: () => toast({ tone: "success", title: "Check your email", description: `We sent a link to ${me.user.email} to set your password.` }),
    onError: (e) => toast({ tone: "error", title: "Could not send the link", description: problemText(e) }),
  });
  const ready = deletionReady(me, { name, forfeit, password, email });
  const server = fieldErrors(del.error);
  const wrongPassword = isApiError(del.error) && del.error.code === "invalid_credentials";
  const formLevel = del.error && !wrongPassword && !server.confirm_workspace_name && !server.confirm_email && !server.password;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (ready) del.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title="Delete your account?"
      description={`Nothing is erased for ${GRACE_DAYS} days. On ${eraseOn} everything below is deleted for good.`}
      icon={<Trash2 />}
      role="alertdialog"
      footer={
        <>
          <Button autoFocus onClick={() => close(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="danger" disabled={!ready} pending={del.isPending} icon={<Trash2 aria-hidden />}>
            Delete account
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 py-1">
        <div className="flex flex-col gap-2">
          <p className="font-medium text-fg">What is erased</p>
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {ERASED.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p>Phone numbers and WhatsApp channels are released. They stop answering calls and may not be available to you again.</p>
          <p>Billing records stay for accounting, without your email.</p>
        </div>
        <div className="rounded-control border border-danger/30 bg-danger-soft px-3.5 py-3 text-[14px] text-danger-text">
          Your remaining balance of <MoneyText value={me.balance_usd} places={3} className="font-medium" /> is forfeited. It cannot be refunded.
        </div>
        <p>
          Until {eraseOn} you can sign in and choose <span className="font-medium text-fg">Keep my account</span> to cancel. Nothing else works in
          that time.
        </p>
        {formLevel ? <FormAlert>{problemMessage(del.error)}</FormAlert> : null}
        <form id={formId} onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
          <Field
            label="Type the workspace name to confirm"
            hint={
              <>
                Type <span className="font-medium text-fg-2">{me.workspace.name}</span> exactly.
              </>
            }
            error={server.confirm_workspace_name}
          >
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
                aria-describedby={describedBy}
                aria-invalid={invalid}
              />
            )}
          </Field>
          <div className="flex items-start gap-3">
            <Checkbox
              checked={forfeit}
              onChange={() => setForfeit((v) => !v)}
              label={`I understand my ${balance} balance is forfeited and can't be refunded`}
            />
            <button type="button" tabIndex={-1} className="cursor-pointer text-left text-[14px] text-fg" onClick={() => setForfeit((v) => !v)}>
              I understand my <MoneyText value={me.balance_usd} places={3} className="font-medium" /> balance is forfeited and can&apos;t be refunded.
            </button>
          </div>
          {hasPassword ? (
            <PasswordField
              label="Your password"
              autoComplete="current-password"
              value={password}
              onChange={setPassword}
              error={wrongPassword ? "That password is not correct." : server.password}
            />
          ) : null}
          {hasPassword && (
            // Google accounts made before passwords were tracked look like they have one; give them a way in.
            <p className="-mt-2 text-[13px] text-fg-3">
              Signed up with Google and never set a password?{" "}
              <Button variant="link" type="button" pending={sendLink.isPending} onClick={() => sendLink.mutate()}>
                Email me a link to set one
              </Button>
            </p>
          )}
          {hasPassword ? null : (
            <Field
              label="Type your email to confirm"
              hint={`You signed in with Google, so there is no password. Type ${me.user.email}.`}
              error={server.confirm_email}
            >
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="off"
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                />
              )}
            </Field>
          )}
        </form>
      </div>
    </Dialog>
  );
}
