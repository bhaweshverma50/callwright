import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { completeGoogleOnce, forgetGoogleFlow, googleFlowNext, isOurGoogleFlow } from "../../api/googleFlow";
import { problemMessage } from "../../api/problems";
import { startSession } from "../../api/session";
import { Skeleton } from "../../components";
import { AUTH_PAGES, safeNext } from "../../lib/paths";
import { AuthLayout } from "./AuthLayout";

const EXPIRED = "This Google sign-in expired or was already used. Start again.";

/**
 * Where Google sends the browser back (`?code=&state=` or `?error=`). Posts the code once, starts
 * the session and replaces this address so the code does not stay in the browser history.
 */
export function GoogleCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const code = params.get("code");
  const state = params.get("state");
  const error = params.get("error");
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (error || !code || !state) return;
    if (!isOurGoogleFlow(state)) {
      forgetGoogleFlow();
      setFailure(EXPIRED);
      return;
    }
    let live = true;
    completeGoogleOnce(code, state).then(
      (s) => {
        if (!live) return;
        const next = safeNext(googleFlowNext());
        forgetGoogleFlow();
        startSession(s);
        navigate(next, { replace: true });
      },
      (e) => live && setFailure(problemMessage(e)),
    );
    return () => {
      live = false;
    };
  }, [code, state, error, navigate]);

  const back = (
    <Link to={AUTH_PAGES.login} className="link-underline font-medium text-accent-text">
      Back to sign in
    </Link>
  );

  if (error) {
    const cancelled = error === "access_denied";
    return (
      <AuthLayout
        title={cancelled ? "Google sign-in was cancelled" : "Google sign-in did not finish"}
        subtitle={
          cancelled
            ? "You did not sign in. Nothing was changed."
            : "Google could not complete the sign-in. Try again, or use your email and password."
        }
        footer={back}
      >
        {null}
      </AuthLayout>
    );
  }

  if (failure || !code || !state) {
    return (
      <AuthLayout title="We could not sign you in with Google" subtitle={failure ?? EXPIRED} footer={back}>
        {null}
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Signing you in" subtitle="Checking with Google and opening your workspace.">
      <div role="status" className="flex flex-col gap-2">
        <span className="sr-only">Signing in</span>
        <Skeleton className="h-3 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </AuthLayout>
  );
}
