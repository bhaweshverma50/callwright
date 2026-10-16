import { EnvelopeSimple } from "@phosphor-icons/react";
import { MailCheck, RefreshCw, UserPlus } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, unwrap } from "../../api/client";
import { fieldErrors, problemMessage } from "../../api/problems";
import { Button, Field, Input } from "../../components";
import { env } from "../../lib/env";
import { AuthLayout } from "./AuthLayout";
import { FormAlert } from "./FormAlert";
import { MIN_PASSWORD, PasswordStrength } from "./PasswordStrength";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Register (T041, US1.1): strength meter, 10-character minimum, then "check your email". */
export function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);

  const register = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/register", { body: { email: email.trim(), password } })),
  });
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/verify-email/resend", { body: { email: email.trim() } })),
  });

  const fe = fieldErrors(register.error);
  const emailErr = fe.email ?? (touched && !EMAIL.test(email.trim()) ? "Enter a valid email address." : undefined);
  const pwErr = fe.password ?? (touched && password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : undefined);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!EMAIL.test(email.trim()) || password.length < MIN_PASSWORD) return;
    register.mutate();
  };

  if (register.isSuccess) {
    const addr = email.trim().toLowerCase();
    return (
      <AuthLayout title="Check your email" subtitle={<>We sent a verification link to <span className="font-medium text-fg">{addr}</span>. It opens your new workspace with $5.00 of trial credit.</>}>
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3 rounded-panel border border-line bg-surface px-4 py-3.5 text-[13.5px] text-fg-2 shadow-1">
            <EnvelopeSimple weight="duotone" className="size-7 shrink-0 text-accent-text" aria-hidden />
            The link works once. If it does not arrive in a few minutes, check spam or send it again.
          </div>
          <div className="flex items-center gap-3">
            <Button pending={resend.isPending} disabled={resend.isSuccess} onClick={() => resend.mutate()} icon={resend.isSuccess ? <MailCheck aria-hidden /> : <RefreshCw aria-hidden />}>
              {resend.isSuccess ? "Link sent again" : "Send it again"}
            </Button>
            <Button variant="ghost" onClick={() => register.reset()}>
              Use a different email
            </Button>
          </div>
          {env.mocks && (
            <p className="rounded-control border border-dashed border-line-strong px-3.5 py-2.5 text-[12.5px] text-fg-3">
              Demo data is on, so no email is sent.{" "}
              <Link className="link-underline text-accent-text" to={`/verify-email?token_hash=${encodeURIComponent(`verify-${addr}`)}`}>
                Open the verification link
              </Link>
            </p>
          )}
        </div>
      </AuthLayout>
    );
  }

  const formError = register.error && Object.keys(fe).length === 0 ? problemMessage(register.error) : null;

  return (
    <AuthLayout
      title="Create your workspace"
      subtitle="Start with $5.00 of trial credit. No card needed until you top up."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="link-underline font-medium text-accent-text">
            Sign in
          </Link>
        </>
      }
    >
      {formError && <FormAlert>{formError}</FormAlert>}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field label="Work email" error={emailErr}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="email"
              autoComplete="email"
              inputSize="lg"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              autoFocus
            />
          )}
        </Field>
        <Field label="Password" error={pwErr} hint={<PasswordStrength password={password} />}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              inputSize="lg"
              minLength={MIN_PASSWORD}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" size="lg" pending={register.isPending} className="mt-1 w-full" icon={<UserPlus aria-hidden />}>
          Create account
        </Button>
        <p className="text-[12px] leading-relaxed text-fg-3">
          By creating an account you accept the{" "}
          <Link to="/terms" className="text-fg-2 underline underline-offset-2 hover:text-fg">
            terms
          </Link>{" "}
          and the{" "}
          <Link to="/privacy" className="text-fg-2 underline underline-offset-2 hover:text-fg">
            privacy policy
          </Link>
          .
        </p>
      </form>
    </AuthLayout>
  );
}
