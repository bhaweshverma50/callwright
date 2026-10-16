import { PhoneCall as PhoneCallDuo, PhoneList, Robot, type Icon as DuoIcon } from "@phosphor-icons/react";
import { Bot, Disc, Gauge, Mail, Wallet } from "lucide-react";
import { motion } from "motion/react";
import { Link } from "react-router";
import { useMe } from "../../api/queries";
import {
  Badge,
  Button,
  InfoRow,
  MoneyText,
  PageHeader,
  Panel,
  PanelRows,
  Skeleton,
  Stepper,
  WorkLayout,
  cn,
  focusRing,
  type Step,
} from "../../components";

interface SetupStep {
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
export function setupSteps(): SetupStep[] {
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

/** Maps setup progress to stepper rows: done steps, then the first open one active, the rest pending. */
export function toStepperSteps(steps: SetupStep[]): Step[] {
  const current = steps.findIndex((s) => !s.done);
  return steps.map((s, i) => ({
    title: s.title,
    description: s.detail,
    icon: <s.icon weight="duotone" aria-hidden />,
    status: s.done ? "done" : i === current ? "active" : "pending",
    action: (
      <Button asChild variant="primary" size="sm">
        <Link to={s.to}>{s.action}</Link>
      </Button>
    ),
  }));
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

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Calls, cost and quality for this workspace. Get your first call on the line to fill it."
        actions={
          <Button asChild variant="secondary" icon={<Bot aria-hidden />}>
            <Link to="/agents">See agents</Link>
          </Button>
        }
      />
      <WorkLayout
        main={
          <section aria-labelledby="setup" className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
            <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-60" />
            <div className="relative px-5 pb-5 pt-6 sm:px-6">
              <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
                <div className="min-w-0">
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
                  className="grad-action h-full origin-left rounded-full"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: done / steps.length }}
                  transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
                />
              </div>
              <div className="-mx-1 mt-5 sm:-mx-2">
                <Stepper label="Setup steps" steps={toStepperSteps(steps)} />
              </div>
            </div>
          </section>
        }
        inspector={
          <Panel title="Workspace" description="What this workspace runs with today." icon={<Gauge />} bodyClassName="p-0">
            <PanelRows as="dl">
              <InfoRow icon={<Wallet />} label="Balance">
                {isPending || !me ? (
                  <Skeleton className="ml-auto h-4 w-20" />
                ) : (
                  <Link to="/billing" className={cn("link-underline rounded-inline text-fg", focusRing)}>
                    <MoneyText value={me.balance_usd} places={3} animate fromZero className="font-medium" />
                  </Link>
                )}
              </InfoRow>
              <InfoRow icon={<Gauge />} label="Calls at once">
                {isPending ? (
                  <Skeleton className="ml-auto h-4 w-8" />
                ) : (
                  <span className="font-mono text-fg tnum">{me?.workspace.concurrency_limit}</span>
                )}
              </InfoRow>
              <InfoRow icon={<Disc />} label="Call recording">
                {me ? (
                  <Badge tone={me.workspace.recording_default ? "accent" : "neutral"}>
                    {me.workspace.recording_default ? "On by default" : "Off by default"}
                  </Badge>
                ) : (
                  <Skeleton className="ml-auto h-4 w-24" />
                )}
              </InfoRow>
              <InfoRow icon={<Mail />} label="Signed in as" title={me?.user.email}>
                {me?.user.email ?? <Skeleton className="ml-auto h-4 w-32" />}
              </InfoRow>
            </PanelRows>
            <p className="border-t border-line px-5 py-3.5 text-[12.5px] leading-relaxed text-fg-3">
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
