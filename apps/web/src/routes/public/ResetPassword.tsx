import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, unwrap } from "../../api/client";
import { isApiError } from "../../api/errors";
import { fieldErrors, problemMessage } from "../../api/problems";
import { KeyRound, Send } from "lucide-react";
import { Button, Field, FormAlert, Input } from "../../components";
import { AuthLayout } from "./AuthLayout";
import { MIN_PASSWORD, PasswordStrength } from "./PasswordStrength";

/** Set a new password from the email link (T041, US1.4). Expired or used links say so. */
export function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token_hash") ?? "";
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);

  const reset = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/password-reset/confirm", { body: { token_hash: token, new_password: pw } })),
    onSuccess: () => navigate("/login?reset=1", { replace: true }),
  });

  const linkDead = !token || (isApiError(reset.error) && reset.error.status === 400);
  if (linkDead) {
    return (
      <AuthLayout
        title="This link has expired"
        subtitle="Reset links work once, for 60 minutes. Ask for a new one and use it soon after it arrives."
        footer={
          <Link to="/login" className="link-underline font-medium text-accent-text">
            Back to sign in
          </Link>
        }
      >
        <Button asChild variant="primary" size="lg" className="w-full" icon={<Send aria-hidden />}>
          <Link to="/forgot-password">Send a new link</Link>
        </Button>
      </AuthLayout>
    );
  }

  const fe = fieldErrors(reset.error);
  const pwErr = fe.new_password ?? (touched && pw.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : undefined);
  const confirmErr = touched && confirm !== pw ? "The two passwords do not match." : undefined;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (pw.length < MIN_PASSWORD || pw !== confirm) return;
    reset.mutate();
  };

  return (
    <AuthLayout title="Choose a new password" subtitle="Signing in with the new password ends every other session.">
      {reset.error && !Object.keys(fe).length ? <FormAlert>{problemMessage(reset.error)}</FormAlert> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field label="New password" error={pwErr} hint={<PasswordStrength password={pw} />}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              inputSize="lg"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              autoFocus
            />
          )}
        </Field>
        <Field label="Repeat it" error={confirmErr}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              inputSize="lg"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" size="lg" pending={reset.isPending} icon={<KeyRound aria-hidden />}>
          Save new password
        </Button>
      </form>
    </AuthLayout>
  );
}
