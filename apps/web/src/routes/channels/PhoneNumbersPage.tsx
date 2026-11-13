import { ChatsCircle, PhoneList } from "@phosphor-icons/react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Bot,
  ChevronRight,
  MessageCircle,
  Network,
  PhoneCall,
  PhoneIncoming,
  Plus,
  Route,
  ShieldCheck,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { useAllAgents, type AgentSummary } from "../../api/agents";
import { problemMessage } from "../../api/problems";
import { Button, EmptyState, FlowChain, PageHeader, Skeleton, TabPanel, Tabs, WorkLayout, cn, toast } from "../../components";
import { ComplianceTab } from "./components/ComplianceTab";
import { ImportNumberDialog } from "./components/ImportNumberDialog";
import { NumberDetailPanel } from "./components/NumberDetailPanel";
import { ActiveCalls, ChannelStatusBadge, TelephonyNotice } from "./components/shared";
import { SipSettingsCard } from "./components/SipSettingsCard";
import { WhatsAppChannelDialog } from "./components/WhatsAppChannelDialog";
import { WhatsAppChannelPanel } from "./components/WhatsAppChannelPanel";
import { usePhoneNumbers, useSipSettings, useWhatsAppChannels, type PhoneNumber, type WhatsAppChannel } from "../../api/channels";

type Tab = "numbers" | "whatsapp" | "compliance";

const PHONE_FLOW = [
  { key: "carrier", label: "Your carrier", icon: <Network aria-hidden /> },
  { key: "callwright", label: "Callwright", icon: <PhoneIncoming aria-hidden /> },
  { key: "agent", label: "Agent", icon: <Bot aria-hidden /> },
];
const WA_FLOW = [
  { key: "whatsapp", label: "WhatsApp", icon: <MessageCircle aria-hidden /> },
  { key: "route", label: "Caller route", icon: <Route aria-hidden /> },
  { key: "agent", label: "Agent", icon: <Bot aria-hidden /> },
];

export function agentName(agents: AgentSummary[] | undefined, id: string | null | undefined): string | null {
  if (!id) return null;
  return agents?.find((a) => a.id === id)?.name ?? "Unknown agent";
}

function AgentLine({ icon, label, name, empty }: { icon: ReactNode; label: string; name: string | null; empty: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-3 text-fg-2 [&_svg]:size-3.5">{icon}</span>
      <span className="w-[62px] shrink-0 text-[12px] text-fg-3">{label}</span>
      <span className={cn("min-w-0 truncate text-[13px]", name ? "font-medium text-fg" : "pr-0.5 italic text-fg-3")}>{name ?? empty}</span>
    </div>
  );
}

function ChannelCard({
  icon,
  title,
  subtitle,
  status,
  lines,
  footer,
  onOpen,
  ariaLabel,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  status: ReactNode;
  lines: ReactNode;
  footer: ReactNode;
  onOpen: () => void;
  ariaLabel: string;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className="flex min-w-0"
    >
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen();
          }
        }}
        aria-label={ariaLabel}
        className="group relative flex min-w-0 flex-1 cursor-pointer flex-col rounded-panel border border-line bg-surface text-left shadow-1 transition-[transform,box-shadow,border-color] duration-200 hover:border-accent/45 focus-visible:border-accent focus-visible:outline-none"
      >
        <div className="flex items-start gap-3 px-5 pb-3.5 pt-4">
          <span className="grid size-10 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text transition-[background-color,color] duration-200 group-hover:bg-accent group-hover:text-white [&_svg]:size-5">
            {icon}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5 pt-px">
            <span className="truncate font-mono text-[15px] font-medium leading-snug text-fg tnum">{title}</span>
            <span className="truncate text-[13px] text-fg-2">{subtitle}</span>
          </div>
          <div className="shrink-0 pt-0.5">{status}</div>
        </div>
        <div className="mx-5 flex flex-col gap-2 border-y border-line py-3">{lines}</div>
        <div className="flex items-center justify-between gap-2 px-5 pb-3 pt-2.5">
          {footer}
          <ChevronRight
            className="size-4 text-fg-3 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-accent-text"
            aria-hidden
          />
        </div>
      </div>
    </motion.div>
  );
}

function NumberCards({ numbers, agents, onOpen }: { numbers: PhoneNumber[]; agents: AgentSummary[] | undefined; onOpen: (n: PhoneNumber) => void }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2">
      <AnimatePresence>
        {numbers.map((n) => (
          <ChannelCard
            key={n.id}
            ariaLabel={`Open ${n.e164}, ${n.label}`}
            icon={<PhoneCall aria-hidden />}
            title={n.e164}
            subtitle={n.label}
            status={<ChannelStatusBadge status={n.status} />}
            onOpen={() => onOpen(n)}
            lines={
              <>
                <AgentLine
                  icon={<ArrowDownLeft aria-hidden />}
                  label="Inbound"
                  name={agentName(agents, n.inbound_agent_id)}
                  empty="No agent: calls declined"
                />
                <AgentLine
                  icon={<ArrowUpRight aria-hidden />}
                  label="Outbound"
                  name={agentName(agents, n.outbound_agent_id)}
                  empty="No default agent"
                />
              </>
            }
            footer={<ActiveCalls count={n.active_call_count} />}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}

function SetupDots({ c }: { c: WhatsAppChannel }) {
  const steps = [
    { done: !!c.credentials_verified_at, label: "Credentials checked" },
    { done: !!c.calling_enabled_at, label: "Calling on" },
    { done: !!c.webhook_verified_at, label: "Callback verified" },
  ];
  const done = steps.filter((s) => s.done).length;
  return (
    <span className="flex items-center gap-2 text-[13px] text-fg-3">
      <span className="flex gap-1" aria-hidden>
        {steps.map((s) => (
          <span key={s.label} className={cn("h-1.5 w-4 rounded-full", s.done ? "bg-accent" : "bg-surface-3")} />
        ))}
      </span>
      {done} of 3 setup steps
    </span>
  );
}

function WhatsAppCards({
  channels,
  agents,
  onOpen,
}: {
  channels: WhatsAppChannel[];
  agents: AgentSummary[] | undefined;
  onOpen: (c: WhatsAppChannel) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 2xl:grid-cols-3">
      <AnimatePresence>
        {channels.map((c) => (
          <ChannelCard
            key={c.id}
            ariaLabel={`Open ${c.label}, ${c.e164}`}
            icon={<MessageCircle aria-hidden />}
            title={c.e164}
            subtitle={c.label}
            status={<ChannelStatusBadge status={c.status} />}
            onOpen={() => onOpen(c)}
            lines={
              <>
                <AgentLine icon={<Bot aria-hidden />} label="Default" name={agentName(agents, c.inbound_agent_id)} empty="No default agent" />
                <AgentLine
                  icon={<Route aria-hidden />}
                  label="Routes"
                  name={c.caller_route_count ? `${c.caller_route_count} caller ${c.caller_route_count === 1 ? "route" : "routes"}` : null}
                  empty="Every caller gets the default"
                />
              </>
            }
            footer={c.status === "active" ? <ActiveCalls count={c.active_call_count} /> : <SetupDots c={c} />}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}

function Hero({
  icon,
  title,
  body,
  action,
  flow,
  flowLabel,
  caption,
}: {
  icon: ReactNode;
  title: string;
  body: ReactNode;
  action: ReactNode;
  flow: typeof PHONE_FLOW;
  flowLabel: string;
  caption: string;
}) {
  return (
    <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
      <div className="relative grid gap-8 px-6 py-10 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
        <EmptyState className="px-0 py-0" icon={icon} title={title} actions={action}>
          {body}
        </EmptyState>
        <div className="rounded-panel border border-line bg-surface-2/70 px-5 py-6">
          <p className="text-[13px] font-medium text-fg">{flowLabel}</p>
          <FlowChain label={flowLabel} nodes={flow} active={flow[1]!.key} flow stack="tight" className="mt-5" />
          <p className="mt-5 text-[13px] leading-relaxed text-fg-2">{caption}</p>
        </div>
      </div>
    </section>
  );
}

const NEEDS = [
  { icon: <PhoneCall aria-hidden />, title: "A number on a SIP trunk", detail: "From any provider that offers SIP trunking, in E.164 form." },
  {
    icon: <Network aria-hidden />,
    title: "The trunk's termination address",
    detail: "Host or IP and port, plus a username and password if it uses them.",
  },
  { icon: <Bot aria-hidden />, title: "A published agent", detail: "It answers inbound calls and talks on the calls you place." },
];

function NeedsPanel() {
  return (
    <section className="rounded-panel border border-line bg-surface shadow-1">
      <header className="border-b border-line px-5 py-3.5">
        <h2 className="text-[14px] font-semibold text-fg">What you need</h2>
        <p className="text-[13px] text-fg-3">Have these ready before you import.</p>
      </header>
      <ol className="flex flex-col gap-4 px-5 py-4">
        {NEEDS.map((n, i) => (
          <motion.li
            key={n.title}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.08 * i, duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="flex items-start gap-3"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-4">{n.icon}</span>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-[14px] font-medium text-fg">{n.title}</span>
              <span className="text-[13px] leading-relaxed text-fg-3">{n.detail}</span>
            </div>
          </motion.li>
        ))}
      </ol>
    </section>
  );
}

function CardsSkeleton() {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2" aria-busy="true" aria-label="Loading">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-[178px] w-full rounded-panel" />
      ))}
    </div>
  );
}

/**
 * Channels (010 T023, T082): phone numbers from your own SIP trunk, WhatsApp voice and the outbound
 * compliance rules. The sidebar entry and the title both read "Channels".
 */
export function PhoneNumbersPage() {
  const [params, setParams] = useSearchParams();
  const tab = (["numbers", "whatsapp", "compliance"].includes(params.get("tab") ?? "") ? params.get("tab") : "numbers") as Tab;
  const setTab = (t: string) => setParams(t === "numbers" ? {} : { tab: t }, { replace: true });
  const numbers = usePhoneNumbers();
  const channels = useWhatsAppChannels();
  const sip = useSipSettings();
  const agents = useAllAgents();
  const [importing, setImporting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [openNumber, setOpenNumber] = useState<string | null>(null);
  const [openChannel, setOpenChannel] = useState<string | null>(null);

  const numberList = numbers.data?.items ?? [];
  const channelList = channels.data?.items ?? [];
  const selectedNumber = numberList.find((n) => n.id === openNumber) ?? null;
  const selectedChannel = channelList.find((c) => c.id === openChannel) ?? null;
  const telephonyOff = sip.data ? !sip.data.telephony_enabled : false;

  const importAction = (
    <Button data-tour="channels-import" variant="primary" icon={<Plus aria-hidden />} onClick={() => setImporting(true)}>
      Import number
    </Button>
  );
  const connectAction = (
    <Button variant="primary" icon={<Plus aria-hidden />} onClick={() => setConnecting(true)}>
      Connect WhatsApp
    </Button>
  );
  const headerAction = tab === "numbers" && numberList.length ? importAction : tab === "whatsapp" && channelList.length ? connectAction : undefined;

  return (
    <>
      <PageHeader
        title="Channels"
        description="Put agents on phone numbers from your own SIP trunk and on WhatsApp, and set the rules outbound calls follow."
        actions={headerAction}
      />
      {telephonyOff && <TelephonyNotice className="mb-5" />}
      <Tabs
        value={tab}
        onValueChange={setTab}
        aria-label="Channels"
        items={[
          { value: "numbers", label: "Numbers", icon: <PhoneCall aria-hidden />, count: numbers.data?.total },
          { value: "whatsapp", label: "WhatsApp", icon: <MessageCircle aria-hidden />, count: channels.data?.items.length },
          { value: "compliance", label: "Compliance", icon: <ShieldCheck aria-hidden /> },
        ]}
      >
        <TabPanel value="numbers" className="pt-6">
          {numbers.isPending ? (
            <CardsSkeleton />
          ) : numbers.isError ? (
            <EmptyState icon={<PhoneList weight="duotone" />} title="Numbers did not load">
              {problemMessage(numbers.error, "phone number")}
            </EmptyState>
          ) : numberList.length === 0 ? (
            <div className="flex flex-col gap-5">
              <Hero
                icon={<PhoneList weight="duotone" />}
                title="Put an agent on a phone number"
                body="Bring a number from any SIP trunk provider, such as Twilio, Telnyx or your own PBX. Callwright sets up routing, answers inbound calls with the agent you choose and places outbound calls from it."
                action={importAction}
                flow={PHONE_FLOW}
                flowLabel="How a call reaches your agent"
                caption="Ringing, busy and unanswered calls are never charged. You pay for connected seconds only."
              />
              <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-2">
                <NeedsPanel />
                <SipSettingsCard />
              </div>
            </div>
          ) : (
            <WorkLayout
              main={<NumberCards numbers={numberList} agents={agents.data} onOpen={(n) => setOpenNumber(n.id)} />}
              inspector={<SipSettingsCard />}
            />
          )}
        </TabPanel>
        <TabPanel value="whatsapp" className="pt-6">
          {channels.isPending ? (
            <CardsSkeleton />
          ) : channels.isError ? (
            <EmptyState icon={<ChatsCircle weight="duotone" />} title="WhatsApp channels did not load">
              {problemMessage(channels.error, "WhatsApp channel")}
            </EmptyState>
          ) : channelList.length === 0 ? (
            <Hero
              icon={<ChatsCircle weight="duotone" />}
              title="Answer WhatsApp calls with an agent"
              body="Connect a WhatsApp Business number with Calling enabled. Customers tap call in WhatsApp and your agent picks up; route specific callers to specific agents."
              action={connectAction}
              flow={WA_FLOW}
              flowLabel="How a WhatsApp call is routed"
              caption="Calls arrive over secure SIP, so transcripts, latency and costs work exactly like phone calls."
            />
          ) : (
            <WhatsAppCards channels={channelList} agents={agents.data} onOpen={(c) => setOpenChannel(c.id)} />
          )}
        </TabPanel>
        <TabPanel value="compliance" className="pt-6">
          <ComplianceTab />
        </TabPanel>
      </Tabs>

      <ImportNumberDialog
        open={importing}
        onOpenChange={setImporting}
        onImported={(n) => {
          toast(
            n.status === "active"
              ? { tone: "success", title: "Number imported", description: `${n.e164} is ready. Attach an inbound agent to answer calls.` }
              : { tone: "error", title: "Number saved, setup failed", description: n.status_detail ?? "Open it to retry setup." },
          );
          setOpenNumber(n.id);
        }}
      />
      <WhatsAppChannelDialog
        open={connecting}
        onOpenChange={setConnecting}
        onCreated={(c) => {
          toast(
            c.status === "error"
              ? { tone: "error", title: "Channel saved, setup failed", description: c.status_detail ?? undefined }
              : { tone: "success", title: "WhatsApp connected", description: "Verify the callback in the Meta app to finish." },
          );
          setOpenChannel(c.id);
        }}
      />
      <NumberDetailPanel number={selectedNumber} open={!!selectedNumber} onOpenChange={(o) => !o && setOpenNumber(null)} />
      <WhatsAppChannelPanel channel={selectedChannel} open={!!selectedChannel} onOpenChange={(o) => !o && setOpenChannel(null)} />
    </>
  );
}
