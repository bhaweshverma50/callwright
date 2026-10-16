import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, unwrap } from "../../api/client";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import type { Session } from "../../api/types";
import { startSession } from "../../app/auth";
import { Button, Field, Input, Skeleton } from "../../components";
import { AuthLayout } from "./AuthLayout";
import { FormAlert } from "./FormAlert";

// A verification link works once. React StrictMode mounts effects twice in development, so
// in-flight requests are shared per token instead of being sent again.
const inflight = new Map<string, Promise<Session>>();
function verifyOnce(token_hash: string) {
  let p = inflight.get(token_hash);
  if (!p) {
    p = unwrap(api.POST("/auth/verify-email", { body: { token_hash } }));
    inflight.set(token_hash, p);
  }
  return p;
}

/** Email link landing (T041, US1.1): verifies, starts the session, opens the dashboard. */
export function VerifyEmail() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token_hash") ?? "";
  const [state, setState] = useState<{ status: "working" } | { status: "failed"; error: unknown }>(() =>
    token ? { status: "working" } : { status: "failed", error: null },
  );

  useEffect(() => {
    if (!token) return;
    let live = true;
    verifyOnce(token).then(
      (s) => {
        if (!live) return;
        startSession(s);
        navigate("/dashboard", { replace: true });
      },
      (error) => live && setState({ status: "failed", error }),
    );
    return () => {
      live = false;
    };
  }, [token, navigate]);

  if (state.status === "working") {
    return (
      <AuthLayout title="Verifying your email" subtitle="Setting up your workspace and trial credit.">
        <div role="status" className="flex flex-col gap-2">
          <span className="sr-only">Verifying</span>
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </AuthLayout>
    );
  }

  const expired = !state.error || (isApiError(state.error) && state.error.status === 400);
  return (
    <AuthLayout
      title={expired ? "This link has expired" : "We could not verify that link"}
      subtitle={expired ? "Verification links work once and expire. Ask for a new one below." : problemMessage(state.error)}
      footer={
        <Link to="/login" className="font-medium text-accent-text underline-offset-4 hover:underline">
          Back to sign in
        </Link>
      }
    >
      <ResendForm />
    </AuthLayout>
  );
}

function ResendForm() {
  const [email, setEmail] = useState("");
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/verify-email/resend", { body: { email: email.trim() } })),
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (email.trim()) resend.mutate();
  };
  if (resend.isSuccess)
    return <FormAlert tone="info">If {email.trim()} has an unverified account, a new link is on its way.</FormAlert>;
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {resend.error ? <FormAlert>{problemMessage(resend.error)}</FormAlert> : null}
      <Field label="Email">
        {({ id, describedBy }) => (
          <Input id={id} type="email" autoComplete="email" inputSize="lg" value={email} onChange={(e) => setEmail(e.target.value)} aria-describedby={describedBy} />
        )}
      </Field>
      <Button type="submit" variant="primary" size="lg" pending={resend.isPending} disabled={!email.trim()}>
        Send a new link
      </Button>
    </form>
  );
}
