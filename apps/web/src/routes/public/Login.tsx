import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { api, unwrap } from "../../api/client";
import { isApiError } from "../../api/errors";
import { fieldErrors, problemMessage } from "../../api/problems";
import { safeNext, startSession, useSignedIn } from "../../app/auth";
import { LogIn } from "lucide-react";
import { Button, Field, Input } from "../../components";
import { env } from "../../lib/env";
import { AuthLayout } from "./AuthLayout";
import { FormAlert } from "./FormAlert";

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
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [resent, setResent] = useState(false);

  const signIn = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/sign-in", { body: { email: email.trim(), password } })),
    onSuccess: (s) => {
      startSession(s);
      navigate(next, { replace: true });
    },
  });
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/verify-email/resend", { body: { email: email.trim() } })),
    onSuccess: () => setResent(true),
  });

  if (signedIn && !signIn.isPending && !signIn.isSuccess) return <Navigate to={next} replace />;

  const err = signIn.error;
  const code = isApiError(err) ? err.code : undefined;
  const fe = fieldErrors(err);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setResent(false);
    signIn.mutate();
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
      {params.get("reset") === "1" && !err && <FormAlert tone="info">Your password was changed. Sign in with the new one.</FormAlert>}
      {err &&
        (code === "email_unverified" ? (
          <FormAlert
            tone="warning"
            action={
              resent ? (
                <span className="text-[12.5px]">Sent. Check your inbox for the new link.</span>
              ) : (
                <Button size="sm" variant="secondary" pending={resend.isPending} onClick={() => resend.mutate()} className="self-start">
                  Send the link again
                </Button>
              )
            }
          >
            Verify your email first. We sent a link to {email || "your address"} when you registered.
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
            <Link to={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`} className="link-underline text-[13px] text-accent-text">
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
        <Button type="submit" variant="primary" size="lg" pending={signIn.isPending} disabled={!email || !password} className="mt-1 w-full" icon={<LogIn aria-hidden />}>
          Sign in
        </Button>
      </form>

      {env.mocks && (
        <p className="mt-5 rounded-control border border-dashed border-line-strong px-3.5 py-2.5 text-[12.5px] text-fg-3">
          Demo data is on. Use <span className="font-medium text-fg-2">ops@halcyon-dental.com</span> with{" "}
          <span className="font-medium text-fg-2">correct-horse-9</span>.{" "}
          <button
            type="button"
            className="link-underline text-accent-text"
            onClick={() => {
              setEmail("ops@halcyon-dental.com");
              setPassword("correct-horse-9");
            }}
          >
            Fill it in
          </button>
        </p>
      )}
    </AuthLayout>
  );
}
