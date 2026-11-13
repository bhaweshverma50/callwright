import { useMutation } from "@tanstack/react-query";
import { KeyRound, Mail, Trash2, UserRound } from "lucide-react";
import { useId, useState } from "react";
import { requestPasswordReset } from "../../api/auth";
import { problemText } from "../../api/problems";
import type { Me } from "../../api/types";
import { Button, FieldRow, InfoRow, Panel, PanelRows, toast } from "../../components";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { DeleteAccountDialog, GRACE_DAYS } from "./DeleteAccountDialog";

/** The signed-in person: email, password, and (at the very bottom of Settings) deleting the account. */
export function AccountPanel({ me }: { me: Me }) {
  const [changing, setChanging] = useState(false);
  const passwordId = useId();
  // An account created through Google has no password: "Set a password" sends the reset link.
  const setPassword = useMutation({
    mutationFn: () => requestPasswordReset(me.user.email),
    onSuccess: () => toast({ tone: "success", title: "Check your email", description: `We sent a link to ${me.user.email} to set your password.` }),
    onError: (e) => toast({ tone: "error", title: "Could not send the link", description: problemText(e) }),
  });
  return (
    <Panel title="Account" description="How you sign in to Callwright." icon={<UserRound />} bodyClassName="p-0">
      <PanelRows>
        <InfoRow icon={<Mail />} label="Email" title={me.user.email}>
          {me.user.email}
        </InfoRow>
        <FieldRow
          inline
          icon={<KeyRound />}
          label="Password"
          htmlFor={passwordId}
          description={
            me.user.has_password
              ? "Changing it signs you out on every other device."
              : "You sign in with Google. Set a password to also sign in with your email."
          }
        >
          {me.user.has_password ? (
            <Button id={passwordId} aria-label="Change password" onClick={() => setChanging(true)}>
              Change password
            </Button>
          ) : (
            <Button id={passwordId} aria-label="Set a password" pending={setPassword.isPending} onClick={() => setPassword.mutate()}>
              Set a password
            </Button>
          )}
        </FieldRow>
      </PanelRows>
      <ChangePasswordDialog open={changing} onOpenChange={setChanging} />
    </Panel>
  );
}

/** The danger area: deleting the account is scheduled, never immediate. */
export function DeleteAccountPanel({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const buttonId = useId();
  return (
    <Panel
      title="Delete account"
      description="Erase this workspace and everything in it."
      icon={<Trash2 />}
      className="border-danger/30"
      bodyClassName="p-0"
    >
      <PanelRows>
        <FieldRow
          inline
          label="Delete this account"
          htmlFor={buttonId}
          description={`Nothing is erased for ${GRACE_DAYS} days. Sign in again before then to keep it.`}
        >
          <Button id={buttonId} aria-label="Delete account" variant="danger" icon={<Trash2 aria-hidden />} onClick={() => setOpen(true)}>
            Delete account
          </Button>
        </FieldRow>
      </PanelRows>
      <DeleteAccountDialog me={me} open={open} onOpenChange={setOpen} />
    </Panel>
  );
}
