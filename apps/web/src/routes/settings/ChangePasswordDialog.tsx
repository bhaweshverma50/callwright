import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { changePassword } from "../../api/account";
import { isApiError } from "../../api/errors";
import { fieldErrors, problemMessage } from "../../api/problems";
import { session } from "../../api/session";
import { Button, Dialog, FormAlert, toast } from "../../components";
import { MIN_PASSWORD, PasswordStrength } from "../public/PasswordStrength";
import { PasswordField } from "./PasswordField";

/**
 * Change password while signed in. The server ends every session and answers with a fresh one for
 * this device, which replaces the stored tokens; other devices are signed out.
 */
export function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);

  const change = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: (fresh) => {
      session.set(fresh);
      close(false);
      toast({ tone: "success", title: "Password changed", description: "Your other devices were signed out." });
    },
  });

  function close(value: boolean) {
    if (!value) {
      setCurrent("");
      setNext("");
      setConfirm("");
      setTouched(false);
      change.reset();
    }
    onOpenChange(value);
  }

  const server = fieldErrors(change.error);
  const wrongCurrent = isApiError(change.error) && change.error.code === "invalid_credentials";
  const currentErr = wrongCurrent ? "Your current password is not correct." : touched && current === "" ? "Enter your current password." : undefined;
  const nextErr =
    server.new_password ??
    (touched && next.length < MIN_PASSWORD
      ? `Use at least ${MIN_PASSWORD} characters.`
      : touched && next === current
        ? "Choose a password different from your current one."
        : undefined);
  const confirmErr = touched && confirm !== next ? "The two passwords do not match." : undefined;
  const formLevel = change.error && !wrongCurrent && !server.new_password;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (current === "" || next.length < MIN_PASSWORD || next === current || confirm !== next) return;
    change.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title="Change password"
      description="Signing in with the new password ends every other session. We email you a notice that it changed."
      icon={<KeyRound />}
      footer={
        <>
          <Button onClick={() => close(false)}>Cancel</Button>
          <Button type="submit" form={formId} variant="primary" pending={change.isPending} icon={<KeyRound aria-hidden />}>
            Change password
          </Button>
        </>
      }
    >
      {formLevel ? <FormAlert>{problemMessage(change.error)}</FormAlert> : null}
      <form id={formId} onSubmit={onSubmit} noValidate className="flex flex-col gap-4 py-1">
        <PasswordField label="Current password" autoComplete="current-password" value={current} onChange={setCurrent} error={currentErr} autoFocus />
        <PasswordField
          label="New password"
          autoComplete="new-password"
          value={next}
          onChange={setNext}
          error={nextErr}
          hint={<PasswordStrength password={next} />}
        />
        <PasswordField label="Repeat the new password" autoComplete="new-password" value={confirm} onChange={setConfirm} error={confirmErr} />
      </form>
    </Dialog>
  );
}
