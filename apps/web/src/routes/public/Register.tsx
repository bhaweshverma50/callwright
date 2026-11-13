import { EnvelopeSimple } from "@phosphor-icons/react";
import { MailCheck, RefreshCw, UserPlus } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { register, resendVerification } from "../../api/auth";
import { fieldErrors, problemMessage } from "../../api/problems";
import { TRIAL_CREDIT } from "../../lib/money";
import { startSession } from "../../api/session";
import { Button, Field, FormAlert, Input } from "../../components";
import { AuthLayout } from "./AuthLayout";
import { MIN_PASSWORD, PasswordStrength } from "./PasswordStrength";
import { demoHints } from "../../lib/demoHints";
import { AUTH_PAGES, DASHBOARD_PATH } from "../../lib/paths";
import { bodyLimits } from "../../lib/contract.gen";
import { env } from "../../lib/env";
import { Turnstile } from "./Turnstile";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Register (T041, US1.1): strength meter, 10-character minimum, then "check your email". When the
 * API verifies accounts at once (AUTH_AUTO_VERIFY_EMAIL on a demo) the response carries session
 * tokens and the user goes straight to the dashboard.
 */
export function Register() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const hints = demoHints();
  const siteKey = env.turnstileSiteKey;
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = useState(0);

  const signUp = useMutation({
    mutationFn: () => register(email.trim(), password, captcha ?? undefined),
    onError: () => {
      // A token works once: ask for a fresh one before the next try.
      if (!siteKey) return;
      setCaptcha(null);
      setCaptchaReset((n) => n + 1);
    },
    onSuccess: (result) => {
      if (result.status !== "signed_in") return;
      startSession(result);
      navigate(DASHBOARD_PATH, { replace: true });
    },
  });
  const resend = useMutation({
    mutationFn: () => resendVerification(email.trim()),
  });

  const fe = fieldErrors(signUp.error);
  const emailErr = fe.email ?? (touched && !EMAIL.test(email.trim()) ? "Enter a valid email address." : undefined);
  const pwErr = fe.password ?? (touched && password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : undefined);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!EMAIL.test(email.trim()) || password.length < MIN_PASSWORD) return;
    if (siteKey && !captcha) return;
    signUp.mutate();
  };

  if (signUp.isSuccess && signUp.data.status !== "signed_in") {
    const addr = email.trim().toLowerCase();
    return (
      <AuthLayout
        title="Check your email"
        subtitle={
          <>
            We sent a verification link to <span className="font-medium text-fg">{addr}</span>. It opens your new workspace with {TRIAL_CREDIT} of
            trial credit.
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3 rounded-panel border border-line bg-surface px-4 py-3.5 text-[14px] text-fg-2 shadow-1">
            <EnvelopeSimple weight="duotone" className="size-7 shrink-0 text-accent-text" aria-hidden />
            The link works once. If it does not arrive in a few minutes, check spam or send it again.
          </div>
          <div className="flex items-center gap-3">
            <Button
              pending={resend.isPending}
              disabled={resend.isSuccess}
              onClick={() => resend.mutate()}
              icon={resend.isSuccess ? <MailCheck aria-hidden /> : <RefreshCw aria-hidden />}
            >
              {resend.isSuccess ? "Link sent again" : "Send it again"}
            </Button>
            <Button variant="ghost" onClick={() => signUp.reset()}>
              Use a different email
            </Button>
          </div>
          {hints && (
            <p className="rounded-control border border-dashed border-line-strong px-3.5 py-2.5 text-[13px] text-fg-3">
              Demo data is on, so no email is sent.{" "}
              <Link
                className="link-underline text-accent-text"
                to={`${AUTH_PAGES.verifyEmail}?token_hash=${encodeURIComponent(hints.verifyToken(addr))}`}
              >
                Open the verification link
              </Link>
            </p>
          )}
        </div>
      </AuthLayout>
    );
  }

  const formError = signUp.error && Object.keys(fe).length === 0 ? problemMessage(signUp.error) : null;

  return (
    <AuthLayout
      title="Create your workspace"
      subtitle={`Start with ${TRIAL_CREDIT} of trial credit. No card needed until you top up.`}
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
              maxLength={bodyLimits["POST /auth/register"].password.maxLength}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        {siteKey && <Turnstile siteKey={siteKey} onToken={setCaptcha} resetKey={captchaReset} />}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          pending={signUp.isPending}
          disabled={Boolean(siteKey) && !captcha}
          className="mt-1 w-full"
          icon={<UserPlus aria-hidden />}
        >
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
