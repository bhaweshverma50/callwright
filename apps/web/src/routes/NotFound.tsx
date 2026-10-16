import { Compass } from "@phosphor-icons/react";
import { LayoutDashboard, Undo2 } from "lucide-react";
import { Link, useLocation } from "react-router";
import { Button, EmptyState, Waveform } from "../components";

/** Catch-all inside the shell (T095, FR-018): no silent redirect, a way back to the dashboard. */
export function NotFound() {
  const { pathname } = useLocation();
  return (
    <div className="max-w-[720px]">
      <Waveform flat bars={80} height={28} className="mt-6 opacity-80" />
      <EmptyState
        icon={<Compass weight="duotone" />}
        title="Page not found"
        actions={
          <Button asChild variant="primary" icon={<LayoutDashboard aria-hidden />}>
            <Link to="/dashboard">Go to dashboard</Link>
          </Button>
        }
      >
        <p>
          Nothing is on the line at{" "}
          <code className="rounded-inline bg-surface-3 px-1.5 py-0.5 font-mono text-[12.5px] text-fg">{pathname}</code>. Check the address, or pick
          an area from the navigation.
        </p>
      </EmptyState>
    </div>
  );
}

/** "This agent was not found" style view for record addresses (US1.7). */
export function RecordNotFound({ kind, backTo, backLabel }: { kind: string; backTo: string; backLabel: string }) {
  return (
    <div className="max-w-[720px]">
      <Waveform flat bars={80} height={28} className="mt-6 opacity-80" />
      <EmptyState
        icon={<Compass weight="duotone" />}
        title={`${kind.charAt(0).toUpperCase()}${kind.slice(1)} not found`}
        actions={
          <Button asChild variant="secondary" icon={<Undo2 aria-hidden />}>
            <Link to={backTo}>{backLabel}</Link>
          </Button>
        }
      >
        <p>This {kind} was not found. It may have been deleted, or the link is wrong.</p>
      </EmptyState>
    </div>
  );
}
