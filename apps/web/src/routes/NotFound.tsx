import { Compass } from "@phosphor-icons/react";
import { Link, useLocation } from "react-router";
import { Button, EmptyState } from "../components";

/** Catch-all inside the shell (T095, FR-018): no silent redirect, a way back to the dashboard. */
export function NotFound() {
  const { pathname } = useLocation();
  return (
    <EmptyState
      icon={<Compass />}
      title="Page not found"
      actions={
        <Button asChild variant="primary">
          <Link to="/dashboard">Go to dashboard</Link>
        </Button>
      }
    >
      <p>
        Nothing lives at <code className="rounded-[4px] bg-surface-3 px-1 py-0.5 font-mono text-[12px] text-fg">{pathname}</code>. Check
        the address, or pick an area from the navigation.
      </p>
    </EmptyState>
  );
}

/** "This agent was not found" style view for record addresses (US1.7). */
export function RecordNotFound({ kind, backTo, backLabel }: { kind: string; backTo: string; backLabel: string }) {
  return (
    <EmptyState
      icon={<Compass />}
      title={`${kind.charAt(0).toUpperCase()}${kind.slice(1)} not found`}
      actions={
        <Button asChild variant="secondary">
          <Link to={backTo}>{backLabel}</Link>
        </Button>
      }
    >
      <p>This {kind} was not found. It may have been deleted, or the link is wrong.</p>
    </EmptyState>
  );
}
