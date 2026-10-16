import { PhoneCall as PhoneCallDuo, PhoneList, Robot, type Icon as DuoIcon } from "@phosphor-icons/react";
import { Bot, Check, Disc, Gauge, Wallet } from "lucide-react";
import { motion } from "motion/react";
import { Link } from "react-router";
import { useMe } from "../../api/queries";
import { Badge, Button, MoneyText, PageHeader, Panel, Reveal, RevealItem, Skeleton, WorkLayout, cn, focusRing } from "../../components";

interface Step {
  title: string;
  detail: string;
  action: string;
  to: string;
  icon: DuoIcon;
  done: boolean;
}

/**
 * The three steps to a first real call, in order. Each step's `done` comes from the feature that
 * owns it (002 agents, 003 test calls, 010 numbers); until those ship nothing reports done.
 */
export function setupSteps(): Step[] {
  return [
    {
      title: "Create an agent",
      detail: "Write what it should do, then pick its speech recognition, model and voice.",
      action: "Create an agent",
      to: "/agents/new",
      icon: Robot,
      done: false,
    },
    {
      title: "Make a test call",
      detail: "Talk to it from the browser. Every turn shows its latency and every second its cost.",
      action: "Make a test call",
      to: "/agents",
      icon: PhoneCallDuo,
      done: false,
    },
    {
      title: "Connect a number",
      detail: "Put the agent on a phone number or SIP trunk so real callers can reach it.",
      action: "Connect a number",
      to: "/phone-numbers",
      icon: PhoneList,
      done: false,
    },
  ];
}

/**
 * Dashboard for a workspace with no calls yet (T043; docs/DESIGN.md section 6): a numbered setup
 * sequence with progress, and the workspace facts in the inspector. Analytics (006) replace the
 * sequence once calls exist. Reads only identity and balance (FR-020).
 */
export function DashboardPlaceholder() {
  const { data: me, isPending } = useMe();
  const steps = setupSteps();
  const done = steps.filter((s) => s.done).length;
  const current = steps.findIndex((s) => !s.done);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Calls, cost and quality for this workspace. Get your first call on the line to fill it."
        actions={
          <Button asChild variant="primary" icon={<Bot aria-hidden />}>
            <Link to="/agents/new">Create an agent</Link>
          </Button>
        }
      />
      <WorkLayout
        main={
          <section aria-labelledby="setup" className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
            <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-70" />
            <div className="relative px-5 pb-2 pt-6 sm:px-8">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <h2 id="setup" className="font-display text-[19px] font-medium tracking-[-0.015em] text-fg">
                    Get your first call on the line
                  </h2>
                  <p className="mt-1.5 text-[13.5px] text-fg-2">Three steps, about ten minutes. Your trial credit covers the test calls.</p>
                </div>
                <p className="text-[13px] text-fg-2" aria-live="polite">
                  <span className="font-mono text-fg tnum">{done}</span> of <span className="font-mono tnum">{steps.length}</span> done
                </p>
              </div>
              <div
                role="progressbar"
                aria-label="Setup progress"
                aria-valuemin={0}
                aria-valuemax={steps.length}
                aria-valuenow={done}
                className="mt-5 h-1.5 overflow-hidden rounded-full bg-surface-3"
              >
                <motion.div
                  className="grad-action h-full rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${(done / steps.length) * 100}%` }}
                  transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
                />
              </div>
            </div>
            <Reveal as="ol" className="relative px-3 pb-4 pt-3 sm:px-5">
              {steps.map((s, i) => {
                const active = i === current;
                return (
                  <RevealItem as="li" key={s.title} className="relative">
                    {i < steps.length - 1 && (
                      <span aria-hidden className="absolute bottom-0 left-[31px] top-[60px] w-px bg-line-strong sm:left-[35px]" />
                    )}
                    <div
                      className={cn(
                        "flex flex-col gap-4 rounded-panel px-3 py-4 transition-colors sm:flex-row sm:items-center",
                        active && "bg-accent-soft/45",
                      )}
                      aria-current={active ? "step" : undefined}
                    >
                      <div className="flex flex-1 items-start gap-4">
                        <span
                          className={cn(
                            "grid size-10 shrink-0 place-items-center rounded-full font-mono text-[14px] font-medium tnum",
                            s.done
                              ? "bg-success-soft text-success-text"
                              : active
                                ? "grad-action text-white shadow-glow"
                                : "border border-line-strong bg-surface text-fg-2",
                          )}
                        >
                          {s.done ? <Check className="size-4" aria-label="Done" /> : i + 1}
                        </span>
                        <div className="flex min-w-0 flex-col gap-1">
                          <h3 className="flex items-center gap-2 text-[15px] font-semibold text-fg">
                            <s.icon weight="duotone" className={cn("size-5", active ? "text-accent-text" : "text-fg-3")} aria-hidden />
                            {s.title}
                          </h3>
                          <p className="max-w-[52ch] text-[13.5px] leading-relaxed text-fg-2">{s.detail}</p>
                        </div>
                      </div>
                      <div className="pl-14 sm:pl-0">
                        {active ? (
                          <Button asChild variant="secondary" size="sm">
                            <Link to={s.to}>{s.action}</Link>
                          </Button>
                        ) : (
                          !s.done && <span className="text-[12.5px] text-fg-3">After step {i}</span>
                        )}
                      </div>
                    </div>
                  </RevealItem>
                );
              })}
            </Reveal>
          </section>
        }
        inspector={
          <Panel title="Workspace" icon={<Gauge />} bodyClassName="p-0">
            <dl className="divide-y divide-line">
              <Fact icon={<Wallet />} label="Balance" loading={isPending}>
                {me && (
                  <Link to="/billing" className={cn("link-underline rounded-inline text-fg", focusRing)}>
                    <MoneyText value={me.balance_usd} places={3} animate fromZero className="text-[15px] font-medium" />
                  </Link>
                )}
              </Fact>
              <Fact icon={<Gauge />} label="Calls at once" loading={isPending}>
                <span className="font-mono text-[15px] font-medium text-fg tnum">{me?.workspace.concurrency_limit}</span>
              </Fact>
              <Fact icon={<Disc />} label="Call recording" loading={isPending}>
                {me && (
                  <Badge tone={me.workspace.recording_default ? "accent" : "neutral"}>
                    {me.workspace.recording_default ? "On by default" : "Off by default"}
                  </Badge>
                )}
              </Fact>
            </dl>
            <p className="border-t border-line px-5 py-3.5 text-[12.5px] leading-relaxed text-fg-3">
              {me ? <>Signed in as {me.user.email}. </> : null}
              Change the name and recording default in{" "}
              <Link to="/settings" className={cn("link-underline text-accent-text", focusRing)}>
                Settings
              </Link>
              .
            </p>
          </Panel>
        }
      />
    </>
  );
}

function Fact({ icon, label, loading, children }: { icon: React.ReactNode; label: string; loading: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3.5">
      <dt className="flex items-center gap-2.5 text-[13px] text-fg-2 [&_svg]:size-4 [&_svg]:text-fg-3">
        {icon}
        {label}
      </dt>
      <dd className="flex min-h-6 items-center">{loading ? <Skeleton className="h-4 w-20" /> : children}</dd>
    </div>
  );
}
