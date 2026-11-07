import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api, unwrap } from "../../api/client";
import { problemMessage } from "../../api/problems";
import { Send } from "lucide-react";
import { Button, Field, FormAlert, Input } from "../../components";
import { env } from "../../lib/env";
import { AuthLayout } from "./AuthLayout";

/** Request a reset link (T041, US1.4). The answer never reveals whether the account exists. */
export function ForgotPassword() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const request = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/password-reset", { body: { email: email.trim() } })),
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (email.trim()) request.mutate();
  };

  const back = (
    <Link to="/login" className="link-underline font-medium text-accent-text">
      Back to sign in
    </Link>
  );

  if (request.isSuccess) {
    const addr = email.trim().toLowerCase();
    return (
      <AuthLayout
        title="Check your email"
        subtitle={
          <>
            If an account exists for <span className="font-medium text-fg">{addr}</span>, it has a reset link. The link works once, for 60 minutes.
          </>
        }
        footer={back}
      >
        {env.mocks && (
          <p className="rounded-control border border-dashed border-line-strong px-3.5 py-2.5 text-[13px] text-fg-3">
            Demo data is on, so no email is sent.{" "}
            <Link className="link-underline text-accent-text" to={`/reset-password?token_hash=${encodeURIComponent(`reset-${addr}`)}`}>
              Open the reset link
            </Link>
          </p>
        )}
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter the email you sign in with and we will send a link to choose a new password."
      footer={back}
    >
      {request.error ? <FormAlert>{problemMessage(request.error)}</FormAlert> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field label="Email">
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="email"
              autoComplete="email"
              inputSize="lg"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-describedby={describedBy}
              autoFocus
            />
          )}
        </Field>
        <Button type="submit" variant="primary" size="lg" pending={request.isPending} disabled={!email.trim()} icon={<Send aria-hidden />}>
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  );
}
