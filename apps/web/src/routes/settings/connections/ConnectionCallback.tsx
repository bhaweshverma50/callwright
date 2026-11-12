import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Cloud } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { CONNECT_RETURN_KEY, completeGoogleConnection, connectionKeys, type Connection } from "../../../api/connections";
import { problemMessage } from "../../../api/problems";
import { Button, EmptyState, Skeleton, toast } from "../../../components";
import { CONNECTIONS_CALLBACK_PATH, CONNECTIONS_PATH, safeNext } from "../../../lib/paths";

// Google's code works once and React StrictMode runs effects twice in development, so the
// request is shared per state instead of being sent again.
const inflight = new Map<string, Promise<Connection>>();
function completeOnce(state: string, code: string | null, error: string | null) {
  let p = inflight.get(state);
  if (!p) {
    p = completeGoogleConnection({ state, ...(error ? { error } : { code: code ?? "" }) });
    inflight.set(state, p);
  }
  return p;
}

function returnPath(): string {
  try {
    const saved = sessionStorage.getItem(CONNECT_RETURN_KEY);
    sessionStorage.removeItem(CONNECT_RETURN_KEY);
    const next = safeNext(saved, CONNECTIONS_PATH);
    return next.startsWith(CONNECTIONS_CALLBACK_PATH) ? CONNECTIONS_PATH : next;
  } catch {
    return CONNECTIONS_PATH;
  }
}

/**
 * Google sends the browser here after sign-in (022 research R4). The page posts the code and state
 * with the user's own session, then returns to where sign-in started.
 */
export function ConnectionCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const state = params.get("state");
  const code = params.get("code");
  const error = params.get("error");
  const [failure, setFailure] = useState<unknown>(state ? null : new Error("missing state"));

  useEffect(() => {
    if (!state) return;
    let live = true;
    completeOnce(state, code, error).then(
      (conn) => {
        if (!live) return;
        qc.invalidateQueries({ queryKey: connectionKeys.all });
        toast({ tone: "success", title: "Google connected", description: conn.account_email });
        navigate(returnPath(), { replace: true });
      },
      (err) => live && setFailure(err),
    );
    return () => {
      live = false;
    };
  }, [state, code, error, navigate, qc]);

  if (!failure) {
    return (
      <div role="status" className="flex max-w-[480px] flex-col gap-3 py-12">
        <span className="flex items-center gap-2 text-[14px] text-fg-2">
          <Cloud className="size-4" /> Finishing Google sign-in
        </span>
        <Skeleton className="h-3 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    );
  }
  const declined = error === "access_denied";
  return (
    <EmptyState
      icon={declined ? <CircleCheck /> : <CircleAlert />}
      title={declined ? "Google access was not granted" : "Google sign-in did not finish"}
      actions={
        <Button asChild variant="primary">
          <Link to={CONNECTIONS_PATH} replace>
            Back to Connections
          </Link>
        </Button>
      }
    >
      {declined ? "No connection was made. You can connect again at any time." : problemMessage(failure, "connection")}
    </EmptyState>
  );
}
