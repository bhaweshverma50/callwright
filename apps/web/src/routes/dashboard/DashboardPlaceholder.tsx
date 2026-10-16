import { ArrowRight, ChartLine, CheckCircle, Circle } from "@phosphor-icons/react";
import { Link } from "react-router";
import { useMe } from "../../api/queries";
import { Badge, EmptyState, Label, MoneyText, PageHeader, Skeleton, cn } from "../../components";
import { toMicros } from "../../lib/money";

/**
 * Dashboard until spec 006 ships (T043): the workspace's real limits and a short setup path.
 * Analytics charts replace the lower half when calls exist.
 */
export function DashboardPlaceholder() {
  const { data: me, isPending } = useMe();
  const funded = me ? (toMicros(me.balance_usd) ?? 0n) > 5_000_000n : false;

  return (
    <>
      <PageHeader title="Dashboard" description={me ? `Signed in as ${me.user.email}` : " "} />

      <dl className="grid grid-cols-1 overflow-hidden rounded-panel border border-line bg-surface shadow-panel sm:grid-cols-3">
        <Stat label="Balance" loading={isPending}>
          {me && <MoneyText value={me.balance_usd} places={3} className="text-[22px] font-medium text-fg" />}
        </Stat>
        <Stat label="Concurrent calls" loading={isPending}>
          <span className="font-mono text-[22px] font-medium text-fg tnum">{me?.workspace.concurrency_limit}</span>
          <span className="ml-1.5 text-[12.5px] text-fg-3">at once</span>
        </Stat>
        <Stat label="Call recording" loading={isPending}>
          {me && <Badge tone={me.workspace.recording_default ? "accent" : "neutral"}>{me.workspace.recording_default ? "On by default" : "Off by default"}</Badge>}
        </Stat>
      </dl>

      <section aria-labelledby="setup" className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div>
          <h2 id="setup" className="mb-3 font-display text-[16px] font-semibold tracking-[-0.01em] text-fg">
            Set up your workspace
          </h2>
          <ol className="flex flex-col gap-1">
            <SetupItem done={funded} to="/billing" title="Add funds" detail="Calls draw from your prepaid balance, billed per second." />
            <SetupItem done={false} to="/pricing" title="Estimate a call" detail="Pick speech, model and voice to see the price per minute." />
            <SetupItem done={false} to="/agents" title="Create an agent" detail="Prompt or flow, then test it from the browser." />
          </ol>
        </div>
        <div className="rounded-panel border border-dashed border-line-strong px-6">
          <EmptyState icon={<ChartLine />} title="No calls yet">
            Call volume, cost per minute, latency and pass rates appear here once your agents take calls.
          </EmptyState>
        </div>
      </section>
    </>
  );
}

function Stat({ label, loading, children }: { label: string; loading: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 border-b border-line px-5 py-4 last:border-0 sm:border-b-0 sm:border-r">
      <dt>
        <Label>{label}</Label>
      </dt>
      <dd className="flex h-8 items-center">{loading ? <Skeleton className="h-5 w-24" /> : children}</dd>
    </div>
  );
}

function SetupItem({ done, to, title, detail }: { done: boolean; to: string; title: string; detail: string }) {
  return (
    <li>
      <Link
        to={to}
        className={cn(
          "group flex items-start gap-3 rounded-panel px-3 py-2.5 transition-colors hover:bg-surface",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        )}
      >
        {done ? (
          <CheckCircle weight="fill" className="mt-0.5 size-4 shrink-0 text-accent-text" aria-label="Done" />
        ) : (
          <Circle className="mt-0.5 size-4 shrink-0 text-fg-3" aria-label="To do" />
        )}
        <span className="flex flex-1 flex-col gap-0.5">
          <span className={cn("text-[13.5px] font-medium", done ? "text-fg-2" : "text-fg")}>{title}</span>
          <span className="text-[12.5px] text-fg-3">{detail}</span>
        </span>
        <ArrowRight className="mt-1 size-3.5 text-fg-3 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
      </Link>
    </li>
  );
}

