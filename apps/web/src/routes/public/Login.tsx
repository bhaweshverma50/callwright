import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { resendVerification, signIn } from "../../api/auth";
import { isApiError } from "../../api/errors";
import { fieldErrors, problemMessage, problemText } from "../../api/problems";
import { endSession, startSession, useSignedIn } from "../../api/session";
import { dateLabel } from "../../lib/format";
import { safeNext } from "../../lib/paths";
import { LogIn } from "lucide-react";
import { Button, Field, FormAlert, Input } from "../../components";
import { mmss, useCooldown } from "../../lib/useCooldown";
import { AuthLayout } from "./AuthLayout";
import { GoogleButton } from "./GoogleButton";
import { demoHints } from "../../lib/demoHints";
import { rememberSignIn } from "../../lib/lastSignIn";
import { LastUsed } from "./LastUsed";

/** The scheduled erase date the delete-account dialog passes along (`?deletion=<ISO time>`), or null for anything else. */
function deletionDate(value: string | null): string | null {
  return value && !Number.isNaN(Date.parse(value)) ? value : null;
}

function retryText(seconds?: number) {
  if (!seconds) return "in a few minutes";
  const at = new Date(Date.now() + seconds * 1000);
  const mins = Math.ceil(seconds / 60);
  return `in ${mins} ${mins === 1 ? "minute" : "minutes"}, at ${at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

/** Sign in (T041, US1.2, US1.3): throttle and unverified states, returns to `?next=`. */
export function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const signedIn = useSignedIn();
  const next = safeNext(params.get("next"));
  const deletion = deletionDate(params.get("deletion"));
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const cooldown = useCooldown(60);
  const hints = demoHints();

  const login = useMutation({
    mutationFn: () => signIn(email.trim(), password),
    onSuccess: (s) => {
      startSession(s);
      rememberSignIn("email");
      navigate(next, { replace: true });
    },
  });
  const resend = useMutation({
    mutationFn: () => resendVerification(email.trim()),
    onSuccess: () => cooldown.restart(),
  });

  // Arriving from "Delete account": the server has ended every session, so drop this device's too.
  useEffect(() => {
    if (deletion && signedIn) endSession();
  }, [deletion, signedIn]);

  if (signedIn && !deletion && !login.isPending && !login.isSuccess) return <Navigate to={next} replace />;

  const err = login.error;
  const code = isApiError(err) ? err.code : undefined;
  const fe = fieldErrors(err);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <AuthLayout
      title="Sign in to Callwright"
      subtitle={params.get("next") ? "Sign in to continue where you left off." : "Welcome back. Your agents kept the lines open."}
      footer={
        <>
          New here?{" "}
          <Link to="/register" className="link-underline font-medium text-accent-text">
            Create an account
          </Link>
        </>
      }
    >
      {deletion && !err && (
        <FormAlert tone="info">
          Your account is scheduled for deletion on {dateLabel(deletion)}. Sign in before then and choose Keep my account to cancel.
        </FormAlert>
      )}
      {params.get("reset") === "1" && !err && <FormAlert tone="info">Your password was changed. Sign in with the new one.</FormAlert>}
      {err &&
        (code === "email_unverified" ? (
          <FormAlert
            tone="warning"
            action={
              <Button
                size="sm"
                variant="secondary"
                pending={resend.isPending}
                disabled={cooldown.left > 0}
                onClick={() => resend.mutate()}
                className="self-start"
              >
                {cooldown.left > 0 ? `Sent. Send again in ${mmss(cooldown.left)}` : "Send the link again"}
              </Button>
            }
          >
            Verify your email first. We sent a link to {email || "your address"} when you registered.
            {resend.error && <span className="mt-1 block text-[13px]">{problemText(resend.error)}</span>}
          </FormAlert>
        ) : isApiError(err) && err.status === 429 ? (
          <FormAlert tone="warning">
            Too many sign-in attempts for this account. You can try again {retryText(err.problem.retry_after_s)}, or reset your password.
          </FormAlert>
        ) : (
          <FormAlert>{problemMessage(err)}</FormAlert>
        ))}

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field label="Work email" error={fe.email}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="email"
              autoComplete="email"
              inputSize="lg"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              autoFocus
            />
          )}
        </Field>
        <Field
          label="Password"
          error={fe.password}
          aside={
            <Link
              to={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`}
              className="link-underline text-[13px] text-accent-text"
            >
              Forgot password?
            </Link>
          }
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="password"
              autoComplete="current-password"
              inputSize="lg"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid}
            />
          )}
        </Field>
        <LastUsed method="email">
          <Button
            type="submit"
            variant="primary"
            size="lg"
            pending={login.isPending}
            disabled={!email || !password}
            className="mt-1 w-full"
            icon={<LogIn aria-hidden />}
          >
            Sign in
          </Button>
        </LastUsed>
      </form>

      <GoogleButton next={params.get("next") ? next : undefined} />

      {hints && (
        <p className="mt-5 rounded-control border border-dashed border-line-strong px-3.5 py-2.5 text-[13px] text-fg-3">
          Demo data is on. Use <span className="font-medium text-fg-2">{hints.email}</span> with{" "}
          <span className="font-medium text-fg-2">{hints.password}</span>.{" "}
          <button
            type="button"
            className="link-underline text-accent-text"
            onClick={() => {
              setEmail(hints.email);
              setPassword(hints.password);
            }}
          >
            Fill it in
          </button>
        </p>
      )}
    </AuthLayout>
  );
}
