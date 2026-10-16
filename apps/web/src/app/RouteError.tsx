import { WarningOctagon } from "@phosphor-icons/react";
import { LayoutDashboard, RotateCw } from "lucide-react";
import { Link, isRouteErrorResponse, useRouteError } from "react-router";
import { problemMessage, traceIdOf } from "../api/problems";
import { Button, EmptyState } from "../components";

/**
 * Global error boundary (FR-019). Shows a plain message and, for server faults, the reference
 * (trace id) support can look up. Never shows status codes, stack traces or server text.
 */
export function RouteError({ inShell = false }: { inShell?: boolean }) {
  const error = useRouteError();
  if (import.meta.env.DEV && !import.meta.env.VITEST) console.error(error);
  const traceId = traceIdOf(error);
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  const message = notFound ? "This page does not exist." : problemMessage(error);

  const body = (
    <EmptyState
      icon={<WarningOctagon weight="duotone" />}
      title={notFound ? "Page not found" : "Something went wrong"}
      actions={
        <>
          <Button variant="primary" icon={<RotateCw aria-hidden />} onClick={() => window.location.reload()}>
            Reload page
          </Button>
          <Button asChild variant="secondary" icon={<LayoutDashboard aria-hidden />}>
            <Link to="/dashboard">Go to dashboard</Link>
          </Button>
        </>
      }
    >
      <p>{message}</p>
      {traceId && (
        <p className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-fg-3">Reference for support</span>
          <code className="select-all rounded-inline border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-fg">{traceId}</code>
        </p>
      )}
    </EmptyState>
  );

  if (inShell) return <div role="alert">{body}</div>;
  return (
    <div role="alert" className="grid min-h-dvh place-items-center bg-bg px-6">
      <div className="w-full max-w-[520px]">{body}</div>
    </div>
  );
}
