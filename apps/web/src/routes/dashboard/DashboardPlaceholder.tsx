import { Bot, Disc, Gauge, Mail, Wallet } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAgents } from "../../api/agents";
import { useHasCalls } from "../../api/calls";
import { useMe } from "../../api/queries";
import { usePhoneNumbers, useWhatsAppChannels } from "../../api/channels";
import { Button, InfoTip, MoneyText, PageHeader, Skeleton, Stepper, cn, focusRing, type Step } from "../../components";
import { AGENTS_PATH, BILLING_PATH, NEW_AGENT_PATH, PHONE_NUMBERS_PATH, SETTINGS_PATH } from "../../lib/paths";

interface SetupStep {
  title: string;
  detail: string;
  action: string;
  to: string;
  done: boolean;
}

/**
 * The three steps to a first real call, in order. This view shows until the first live call;
 * "Connect a number" is done once a phone number or WhatsApp channel has an agent (010).
 */
export function setupSteps({
  hasAgent = false,
  hasTestCall = false,
  hasNumber = false,
}: { hasAgent?: boolean; hasTestCall?: boolean; hasNumber?: boolean } = {}): SetupStep[] {
  return [
    {
      title: "Create an agent",
      detail: "Write what it should do, then pick its speech recognition, model and voice.",
      action: "Create an agent",
      to: NEW_AGENT_PATH,
      done: hasAgent,
    },
    {
      title: "Make a test call",
      detail: "Talk to it from the browser. Every turn shows its latency and every second its cost.",
      action: "Make a test call",
      to: AGENTS_PATH,
      done: hasTestCall,
    },
    {
      title: "Connect a number",
      detail: "Put the agent on a phone number or SIP trunk so real callers can reach it.",
      action: "Connect a number",
      to: PHONE_NUMBERS_PATH,
      done: hasNumber,
    },
  ];
}

/** Maps setup progress to stepper rows: done steps, then the first open one active, the rest pending. */
export function toStepperSteps(steps: SetupStep[]): Step[] {
  const current = steps.findIndex((s) => !s.done);
  return steps.map((s, i) => ({
    title: s.title,
    description: s.detail,
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
  const agents = useAgents("", null, 1);
  const testCalls = useHasCalls("test");
  const numbers = usePhoneNumbers();
  const whatsapp = useWhatsAppChannels();
  const hasNumber =
    (numbers.data?.items ?? []).some((n) => n.status !== "draining" && (n.inbound_agent_id || n.outbound_agent_id)) ||
    (whatsapp.data?.items ?? []).some((c) => c.status !== "draining" && c.inbound_agent_id);
  const steps = setupSteps({ hasAgent: (agents.data?.total ?? 0) > 0, hasTestCall: testCalls.data === true, hasNumber });
  const done = steps.filter((s) => s.done).length;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Calls, cost and quality for this workspace. Get your first call on the line to fill it."
        actions={
          <Button asChild variant="secondary" icon={<Bot aria-hidden />}>
            <Link to={AGENTS_PATH}>See agents</Link>
          </Button>
        }
      />
      <div className="flex flex-col gap-6">
        <section aria-labelledby="setup" className="rounded-feature border border-line bg-surface shadow-2">
          {/* Two columns: what this is and how far along, then the steps themselves. */}
          <div className="grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-7 px-5 py-6 sm:px-7 sm:py-7 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <div className="flex min-w-0 flex-col">
              <h2 id="setup" className="font-display text-[19px] tracking-[-0.015em] text-fg">
                Get your first call on the line
              </h2>
              <p className="mt-2 max-w-[44ch] text-[14px] leading-relaxed text-fg-2">
                Three steps, about ten minutes. Your trial credit covers the test calls.
              </p>
              <div className="mt-6">
                <p className="text-[13px] text-fg-2" aria-live="polite">
                  <span className="font-mono text-fg tnum">{done}</span> of <span className="font-mono tnum">{steps.length}</span> done
                </p>
                <div
                  role="progressbar"
                  aria-label="Setup progress"
                  aria-valuemin={0}
                  aria-valuemax={steps.length}
                  aria-valuenow={done}
                  className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-surface-3"
                >
                  <motion.div
                    className="bg-accent h-full origin-left rounded-full"
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: done / steps.length }}
                    transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
                  />
                </div>
              </div>
            </div>
            <Stepper label="Setup steps" steps={toStepperSteps(steps)} />
          </div>
        </section>

        {/* Workspace facts as one strip of equal cells; the 1px gaps on the line colour draw the rules. */}
        <section aria-label="Workspace" className="overflow-hidden rounded-panel border border-line bg-line shadow-1">
          <dl className="grid grid-cols-1 gap-px sm:grid-cols-2 xl:grid-cols-4">
            <Fact icon={<Wallet />} label="Balance" hint="Prepaid credit for calls and features. New calls stop at $0.000.">
              {isPending || !me ? (
                <Skeleton className="h-5 w-20" />
              ) : (
                <Link to={BILLING_PATH} className={cn("link-underline rounded-inline font-mono text-fg tnum", focusRing)}>
                  <MoneyText value={me.balance_usd} places={3} animate fromZero className="font-medium" />
                </Link>
              )}
            </Fact>
            <Fact
              icon={<Gauge />}
              label="Calls at once"
              hint="The most calls this workspace can have in progress at the same moment. A new call past the limit is refused, and its record says why."
            >
              {isPending ? <Skeleton className="h-5 w-8" /> : <span className="font-mono text-fg tnum">{me?.workspace.concurrency_limit}</span>}
            </Fact>
            <Fact icon={<Disc />} label="Call recording" hint="The default for agents set to follow the workspace. Each agent can override it.">
              {me ? (
                <Link to={SETTINGS_PATH} className={cn("link-underline rounded-inline text-fg", focusRing)}>
                  {me.workspace.recording_default ? "On by default" : "Off by default"}
                </Link>
              ) : (
                <Skeleton className="h-5 w-24" />
              )}
            </Fact>
            <Fact icon={<Mail />} label="Signed in as">
              {me ? (
                <span className="block truncate text-fg" title={me.user.email}>
                  {me.user.email}
                </span>
              ) : (
                <Skeleton className="h-5 w-32" />
              )}
            </Fact>
          </dl>
        </section>
      </div>
    </>
  );
}

/** One cell of the workspace strip: icon and label on top, the value under it. */
function Fact({ icon, label, hint, children }: { icon: ReactNode; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 bg-surface px-5 py-4">
      <dt className="flex items-center gap-2 text-[13px] text-fg-3 [&_svg]:size-4">
        {icon}
        {label}
        {hint && <InfoTip label={`About ${label.toLowerCase()}`}>{hint}</InfoTip>}
      </dt>
      <dd className="min-w-0 text-[15px]">{children}</dd>
    </div>
  );
}
