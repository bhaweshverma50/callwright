import { FolderOpen, PhoneCall as PhoneCallDuo, PhoneList, Robot } from "@phosphor-icons/react";
import { BrainCircuit, Captions, Disc, Ear, Gauge, Mail, Mic, Moon, Play, Plus, Shuffle, Sun, Trash2, Volume2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { resolvedTheme, setThemePref, useThemePref } from "../../app/theme";
import {
  Badge,
  Button,
  FlowChain,
  Chip,
  ConfirmDialog,
  CostBreakdownCard,
  Dialog,
  Drawer,
  EmptyState,
  Field,
  IconButton,
  Input,
  Kbd,
  LatencyChip,
  Logo,
  LogoLoader,
  MoneyText,
  OnAir,
  Pagination,
  Reveal,
  RevealItem,
  Select,
  InfoRow,
  Panel,
  PanelRows,
  Skeleton,
  Slider,
  Segmented,
  ChoiceGroup,
  Stepper,
  Switch,
  SwitchControl,
  TabPanel,
  Table,
  Tabs,
  Textarea,
  Ticker,
  Waveform,
  Composer,
  ThinkingIndicator,
  toast,
  type FlowNode,
  type Column,
} from "../../components";
import { WebCallPanel } from "../../components/WebCallPanel";
import type { MockOptions } from "../../components/webCall";
import { formatUsd } from "../../lib/money";
import { referenceBreakdown } from "../public/reference";

const SWATCHES = [
  ["bg (paper / ink)", "--bg"],
  ["surface", "--surface"],
  ["surface-2", "--surface-2"],
  ["surface-3", "--surface-3"],
  ["border", "--border"],
  ["text", "--text"],
  ["text-2", "--text-2"],
  ["text-3", "--text-3"],
  ["accent (cobalt)", "--accent"],
  ["accent-soft", "--accent-soft"],
  ["on-air", "--on-air"],
  ["success", "--success"],
  ["warning", "--warning"],
  ["danger", "--danger"],
] as const;

const NODES: FlowNode[] = [
  { key: "caller", label: "Caller", icon: <Mic aria-hidden /> },
  { key: "stt", label: "Speech to text", icon: <Captions aria-hidden /> },
  { key: "llm", label: "Model", icon: <BrainCircuit aria-hidden /> },
  { key: "tts", label: "Voice", icon: <Volume2 aria-hidden /> },
  { key: "hears", label: "Caller hears", icon: <Ear aria-hidden /> },
];

interface Row {
  id: string;
  agent: string;
  duration: string;
  cost: string;
}
const ROWS: Row[] = [
  { id: "call_01JA8Z3QK0X7", agent: "Front desk", duration: "4:31", cost: "0.477000" },
  { id: "call_01JA8Z4C9M2R", agent: "Billing line", duration: "1:34", cost: "0.110000" },
  { id: "call_01JA8Z5TT6WB", agent: "Front desk", duration: "6:52", cost: "0.731000" },
  { id: "call_01JA8Z6PFJ1D", agent: "After hours", duration: "0:12", cost: "0.015000" },
];
const COLS: Column<Row>[] = [
  { key: "id", header: "Call", cell: (r) => <span className="font-mono text-[12px] text-fg-2">{r.id}</span> },
  { key: "agent", header: "Agent", cell: (r) => r.agent },
  { key: "duration", header: "Duration", numeric: true, cell: (r) => r.duration },
  { key: "cost", header: "Cost", numeric: true, cell: (r) => <MoneyText value={r.cost} places={3} /> },
];

/** Scenarios for the simulated test call (module level so the options keep their identity). */
const CALL_SCENARIOS: Record<string, { label: string; options: MockOptions }> = {
  ok: { label: "Call connects", options: {} },
  "mic-denied": { label: "Microphone blocked", options: { microphone: "denied" } },
  "mic-missing": { label: "No microphone", options: { microphone: "unavailable" } },
  credit: { label: "Not enough credit", options: { refuseWith: 402 } },
  limit: { label: "Concurrency limit", options: { refuseWith: 429 } },
  connect: { label: "Room does not answer", options: { failConnect: true } },
};

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="border-t border-line py-10">
      <h2 className="font-display text-[18px] font-medium tracking-[-0.015em] text-fg">{title}</h2>
      {note && <p className="mt-1.5 max-w-[70ch] text-[13.5px] text-fg-2">{note}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

function Demo({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-5 shadow-1">
      <p className="text-[12.5px] font-medium text-fg-3">{name}</p>
      <div className="flex min-h-16 flex-1 flex-col justify-center">{children}</div>
    </div>
  );
}

/** Design-system gallery at /dev/components: every primitive and motion effect, in the current theme. */
export function ComponentsGallery() {
  const pref = useThemePref();
  const theme = resolvedTheme(pref);
  const [select, setSelect] = useState("nova-3");
  const [slider, setSlider] = useState(12_000);
  const [sw, setSw] = useState(true);
  const [tab, setTab] = useState("one");
  const [dialog, setDialog] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [chip, setChip] = useState("100");
  const [page, setPage] = useState(2);
  const [ticker, setTicker] = useState(96_042_000);
  const [revealKey, setRevealKey] = useState(0);
  const [items, setItems] = useState([1, 2, 3]);
  const [chainActive, setChainActive] = useState(2);
  const [gauge, setGauge] = useState(0.62);
  const [callScenario, setCallScenario] = useState("ok");
  const [speaker, setSpeaker] = useState("agent");
  const [nc, setNc] = useState("vi");
  const [sens, setSens] = useState(0.9);

  return (
    <div className="min-h-dvh bg-bg">
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-line bg-bg/80 px-4 backdrop-blur-md sm:px-6">
        <Link to="/" aria-label="Home">
          <Logo />
        </Link>
        <Button
          variant="secondary"
          size="sm"
          icon={theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
          onClick={() => setThemePref(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "Light" : "Dark"} theme
        </Button>
      </header>
      <main id="main" className="mx-auto max-w-[1120px] px-4 pb-24 pt-12 sm:px-6">
        <h1 className="font-display text-[30px] font-semibold tracking-[-0.03em] text-fg">Components</h1>
        <p className="mt-3 max-w-[70ch] text-[14px] leading-relaxed text-fg-2">
          The signal chain system: ink and paper, one cobalt action colour with a cobalt to violet gradient on primary actions, on-air red for live
          state only, and the heat ramp inside data visualisation. Unbounded for display, Geist for interface text, Geist Mono for figures. Rules live
          in docs/DESIGN.md.
        </p>

        <Section title="Tokens">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {SWATCHES.map(([name, v]) => (
              <div key={name} className="flex flex-col gap-1.5">
                <span className="h-12 rounded-control border border-line" style={{ background: `var(${v})` }} />
                <span className="text-[12px] text-fg-2">{name}</span>
              </div>
            ))}
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <span className="grad-action h-12 rounded-control" />
              <span className="text-[12px] text-fg-2">Action gradient, cobalt to violet (primary buttons, logo, switches, the active step)</span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="grad-heat h-12 rounded-control" />
              <span className="text-[12px] text-fg-2">Heat ramp (data visualisation, chain links, highlight borders)</span>
            </div>
          </div>
          <div className="mt-8 grid gap-6 sm:grid-cols-3">
            <p className="font-display text-[28px] font-semibold tracking-[-0.03em] text-fg">Unbounded</p>
            <p className="text-[14px] leading-relaxed text-fg">Geist 14 for interface and body text, sentence case everywhere.</p>
            <p className="font-mono text-[14px] text-fg tnum">$1,234.567 / 0.0085 / 640 ms</p>
          </div>
          <div className="mt-6 flex flex-wrap items-end gap-6">
            <div className="h-10 w-24 rounded-inline border border-line bg-surface" title="Inline 4px" />
            <div className="h-10 w-24 rounded-control border border-line bg-surface" title="Control 8px" />
            <div className="h-10 w-24 rounded-panel border border-line bg-surface shadow-1" title="Work surface 12px" />
            <div className="h-10 w-24 rounded-feature border border-line bg-surface shadow-2" title="Feature 20px" />
            <span className="text-[12.5px] text-fg-3">Radius and elevation by hierarchy: inline, control, work surface, feature</span>
          </div>
        </Section>

        <Section title="Buttons">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" icon={<Plus aria-hidden />}>
              Create agent
            </Button>
            <Button>Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger" icon={<Trash2 aria-hidden />}>
              Delete
            </Button>
            <Button variant="link">Text link</Button>
            <Button variant="primary" pending>
              Saving
            </Button>
            <Button variant="primary" disabled>
              Disabled
            </Button>
            <Button size="sm">Small</Button>
            <Button size="lg" variant="primary">
              Large
            </Button>
            <IconButton label="Open folder">
              <FolderOpen className="size-4" aria-hidden />
            </IconButton>
          </div>
        </Section>

        <Section title="AI" note="The composer every assistant uses, and the line shown while a model works.">
          <div className="grid gap-6 sm:grid-cols-2">
            <ThinkingIndicator label="Writing" verbs={["Reading your prompt", "Drafting", "Shaping the steps", "Tightening the wording"]} />
            <GalleryComposer />
          </div>
        </Section>

        <Section title="Inputs">
          <div className="grid gap-5 sm:grid-cols-3">
            <Field label="Workspace name" hint="Shown in the top bar.">
              {({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} defaultValue="Halcyon Dental Group" />}
            </Field>
            <Field label="Amount" error="The minimum top-up is $5.">
              {({ id, describedBy, invalid }) => (
                <Input id={id} prefix="$" className="font-mono" aria-describedby={describedBy} aria-invalid={invalid} defaultValue="4" />
              )}
            </Field>
            <Field label="Disabled">{({ id }) => <Input id={id} disabled defaultValue="Read only" />}</Field>
            <Field label="Speech to text">
              {({ id }) => (
                <Select
                  id={id}
                  value={select}
                  onValueChange={setSelect}
                  groups={[
                    {
                      label: "Deepgram",
                      options: [
                        { value: "nova-3", label: "Nova-3", meta: "$0.0085/m" },
                        { value: "nova-2", label: "Nova-2", meta: "$0.0058/m" },
                      ],
                    },
                    { label: "AssemblyAI", options: [{ value: "us", label: "Universal Streaming", meta: "$0.0030/m" }] },
                  ]}
                />
              )}
            </Field>
            <Field label="Greeting" className="sm:col-span-2">
              {({ id }) => <Textarea id={id} defaultValue="Thanks for calling Halcyon Dental, this is Mira. How can I help?" />}
            </Field>
          </div>
          <div className="mt-6 grid gap-6 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <span className="text-[13px] text-fg-2">
                Tokens per minute <span className="font-mono text-fg tnum">{slider.toLocaleString()}</span>
              </span>
              <Slider aria-label="Tokens" tone="heat" value={slider} min={0} max={80_000} step={1_000} onValueChange={setSlider} />
            </div>
            <Switch checked={sw} onCheckedChange={setSw} label="Record calls by default" description="Agents can override this." />
          </div>
        </Section>

        <Section
          title="Choices"
          note="Segmented for short exclusive options, choice cards when each option needs a description; selection is a tint and an outline, never a side stripe."
        >
          <div className="grid gap-6 sm:grid-cols-2">
            <div className="flex flex-col gap-4">
              <Segmented
                aria-label="Who speaks first"
                value={speaker}
                onValueChange={setSpeaker}
                options={[
                  { value: "agent", label: "Agent" },
                  { value: "user", label: "Caller" },
                ]}
              />
              <div className="flex flex-col gap-2">
                <span className="text-[13px] text-fg-2">
                  Interruption sensitivity <span className="font-mono text-fg tnum">{sens.toFixed(2)}</span>
                </span>
                <Slider
                  aria-label="Interruption sensitivity"
                  value={sens}
                  min={0}
                  max={1}
                  step={0.05}
                  onValueChange={setSens}
                  marks={[
                    { value: 0, label: "Low" },
                    { value: 0.5, label: "Medium" },
                    { value: 1, label: "High" },
                  ]}
                />
              </div>
            </div>
            <ChoiceGroup
              aria-label="Noise cancellation"
              size="sm"
              columns={1}
              value={nc}
              onValueChange={setNc}
              options={[
                { value: "vi", title: "Voice isolation", description: "Removes background noise and other voices.", meta: "$0.0000/min" },
                { value: "off", title: "Off", description: "The caller's audio goes to speech recognition untouched." },
              ]}
            />
          </div>
        </Section>

        <Section title="Badges, chips and money">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>Draft</Badge>
            <Badge tone="accent">Published</Badge>
            <Badge tone="success">Passed</Badge>
            <Badge tone="warning">Surcharge</Badge>
            <Badge tone="danger">Failed</Badge>
            <span className="mx-2 h-5 w-px bg-line" />
            {["25", "100", "500"].map((v) => (
              <Chip key={v} selected={chip === v} onClick={() => setChip(v)}>
                ${v}
              </Chip>
            ))}
            <span className="mx-2 h-5 w-px bg-line" />
            <Kbd>[</Kbd>
            <span className="text-[13px] text-fg-3">toggles the sidebar</span>
          </div>
          <div className="mt-5 flex flex-wrap items-baseline gap-6">
            <MoneyText value="1234.567891" places={3} className="text-[22px] text-fg" />
            <MoneyText value="25.000000" places={3} signed toned />
            <MoneyText value="-0.477000" places={3} signed toned />
          </div>
        </Section>

        <Section
          title="Signal visuals"
          note="The chain, the waveform, per-turn latency and the on-air indicator. Heat ramp colours appear only here."
        >
          <div className="grid gap-4 md:grid-cols-2">
            <Demo name="Waveform, live">
              <Waveform bars={64} progress={0.6} live height={48} />
            </Demo>
            <Demo name="Latency chip and on-air">
              <div className="flex flex-wrap items-center gap-4">
                <LatencyChip latency={{ stt: 160, llm: 310, tts: 140 }} />
                <OnAir label="Live call" />
              </div>
            </Demo>
            <Demo name="Flow chain, active node and flowing links">
              <FlowChain nodes={NODES} active="llm" flow />
            </Demo>
            <Demo name="Console surface">
              <div className="rounded-feature bg-console p-4">
                <Waveform bars={48} progress={0.4} onConsole height={32} />
                <div className="mt-3 flex items-center justify-between">
                  <OnAir onConsole />
                  <LatencyChip latency={{ stt: 150, llm: 280, tts: 130 }} onConsole />
                </div>
              </div>
            </Demo>
          </div>
        </Section>

        <Section
          title="Test call panel"
          note="WebCallPanel checks the microphone first, then requests the session, then joins the room, so a blocked microphone never creates a call. Here it plays a simulated call on timers; pick a scenario to see refusals and errors."
        >
          <div className="grid gap-6 lg:grid-cols-[minmax(0,560px)_minmax(0,1fr)]">
            <WebCallPanel
              key={callScenario}
              agentId="agt_01JABCDEF0123456789ABCDEFG"
              mode="mock"
              mockOptions={CALL_SCENARIOS[callScenario]?.options}
            />
            <Field label="Scenario" hint="Restarts the panel with the chosen outcome." className="max-w-[280px]">
              {({ id, describedBy }) => (
                <Select
                  id={id}
                  describedBy={describedBy}
                  value={callScenario}
                  onValueChange={setCallScenario}
                  options={Object.entries(CALL_SCENARIOS).map(([value, s]) => ({ value, label: s.label }))}
                />
              )}
            </Field>
          </div>
        </Section>

        <Section
          title="Motion"
          note="Every effect animates transform and opacity (plus SVG dash offset) and respects reduced motion. Hover, press and focus the demos."
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Demo name="Number ticker">
              <div className="flex items-center justify-between gap-3">
                <MoneyText value={BigInt(ticker)} places={3} animate className="text-[24px] font-medium text-fg" />
                <IconButton label="New value" onClick={() => setTicker(Math.round(Math.random() * 200_000_000))}>
                  <Shuffle className="size-4" aria-hidden />
                </IconButton>
              </div>
            </Demo>
            <Demo name="Staggered reveal">
              <div className="flex items-center gap-3">
                <Reveal key={revealKey} className="flex flex-1 gap-2">
                  {[0, 1, 2, 3].map((i) => (
                    <RevealItem key={i} className="h-10 flex-1 rounded-control bg-accent-soft" />
                  ))}
                </Reveal>
                <IconButton label="Replay reveal" onClick={() => setRevealKey((k) => k + 1)}>
                  <Play className="size-4" aria-hidden />
                </IconButton>
              </div>
            </Demo>
            <Demo name="List enter and exit">
              <div className="flex items-start gap-3">
                <ul className="flex flex-1 flex-col gap-1.5">
                  <AnimatePresence initial={false}>
                    {items.map((n) => (
                      <motion.li
                        key={n}
                        layout
                        initial={{ opacity: 0, y: -6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: 12 }}
                        className="rounded-control border border-line bg-surface-2 px-3 py-1.5 text-[13px] text-fg-2"
                      >
                        Call {n}
                      </motion.li>
                    ))}
                  </AnimatePresence>
                </ul>
                <div className="flex flex-col gap-1">
                  <IconButton label="Add row" onClick={() => setItems((x) => [Math.max(0, ...x) + 1, ...x].slice(0, 4))}>
                    <Plus className="size-4" aria-hidden />
                  </IconButton>
                  <IconButton label="Remove row" onClick={() => setItems((x) => x.slice(1))}>
                    <Trash2 className="size-4" aria-hidden />
                  </IconButton>
                </div>
              </div>
            </Demo>
            <Demo name="Hero CTA idle sheen (one pass every 7 s)">
              <Button variant="primary" idleSheen icon={<Plus aria-hidden />}>
                Create account
              </Button>
            </Demo>
            <Demo name="Ripple, press and sheen (press and hover)">
              <Button variant="primary" icon={<Play aria-hidden />}>
                Make a test call
              </Button>
            </Demo>
            <Demo name="Card lift with glow (hover)">
              <div className="lift rounded-panel border border-line bg-surface p-4 text-[13px] text-fg-2 shadow-1">Front desk agent</div>
            </Demo>
            <Demo name="Animated link underline">
              <a href="#motion" className="link-underline self-start text-[14px] text-accent-text">
                Open the calculator
              </a>
            </Demo>
            <Demo name="Chain flow (click to move)">
              <button type="button" className="cursor-pointer text-left" onClick={() => setChainActive((a) => (a + 1) % NODES.length)}>
                <FlowChain nodes={NODES} active={NODES[chainActive]!.key} flow size="sm" stack="never" />
              </button>
            </Demo>
            <Demo name="Gauge arc">
              <div className="flex items-center gap-4">
                <svg viewBox="0 0 120 64" className="w-28" aria-hidden>
                  <defs>
                    <linearGradient id="gal-arc" x1="10" x2="110" y1="0" y2="0" gradientUnits="userSpaceOnUse">
                      <stop offset="0" stopColor="var(--heat-1)" />
                      <stop offset="0.55" stopColor="var(--heat-2)" />
                      <stop offset="1" stopColor="var(--heat-3)" />
                    </linearGradient>
                  </defs>
                  <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="var(--surface-3)" strokeWidth="8" strokeLinecap="round" />
                  <motion.path
                    d="M 10 60 A 50 50 0 0 1 110 60"
                    fill="none"
                    stroke="url(#gal-arc)"
                    strokeWidth="8"
                    strokeLinecap="round"
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: gauge }}
                    transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
                  />
                </svg>
                <Ticker value={Math.round(gauge * 914)} format={(n) => `${Math.round(n)} min`} className="font-mono text-[16px] text-fg" />
                <IconButton label="New gauge value" onClick={() => setGauge(Math.round(Math.random() * 100) / 100)}>
                  <Shuffle className="size-4" aria-hidden />
                </IconButton>
              </div>
            </Demo>
            <Demo name="Animated border on focus">
              <div className="live-border rounded-panel border border-line bg-surface p-3">
                <Input aria-label="Focus me" placeholder="Focus this field" />
              </div>
            </Demo>
            <Demo name="Logo mark (hover)">
              <Link to="/" className="self-start">
                <Logo />
              </Link>
            </Demo>
            <Demo name="On-air pulse">
              <OnAir label="Recording" />
            </Demo>
            <Demo name="Shimmer skeleton">
              <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
              </div>
            </Demo>
          </div>
          <dl className="mt-6 grid gap-x-8 gap-y-2 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
            {[
              ["Sheen pass", "560 ms, cubic-bezier(0.22, 1, 0.36, 1), on hover or keyboard focus"],
              ["Hero idle sheen", "one pass every 7 s, hero CTA only"],
              ["Press", "scale 0.975 for 90 ms, plus the ripple"],
              ["Skeleton shimmer", "1.3 s per cycle, ease-in-out, stops when content arrives"],
              ["Route transition", "220 ms fade and 6px rise"],
              ["Ticker", "about 700 ms, ease-out, ends on the exact figure"],
            ].map(([k, v]) => (
              <div key={k} className="flex flex-col gap-0.5 border-t border-line pt-2">
                <dt className="font-medium text-fg">{k}</dt>
                <dd className="text-fg-3">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-[12.5px] text-fg-3">
            Route transitions (fade and rise), drawers, dialogs, menus and toasts animate on open and close; open the overlays below to see them.
            Ticker values end on the exact figure, for example {formatUsd(BigInt(ticker), { places: 3 })}.
          </p>
        </Section>

        <Section
          title="Stepper"
          note="Numbered because order matters. One centre axis, a continuous connector, done steps fill the segment below them."
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <Demo name="First step active">
              <Stepper
                label="Setup, nothing done"
                steps={[
                  {
                    title: "Create an agent",
                    description: "Write what it should do.",
                    icon: <Robot weight="duotone" />,
                    status: "active",
                    action: (
                      <Button size="sm" variant="primary">
                        Create an agent
                      </Button>
                    ),
                  },
                  {
                    title: "Make a test call",
                    description: "Talk to it from the browser.",
                    icon: <PhoneCallDuo weight="duotone" />,
                    status: "pending",
                  },
                  { title: "Connect a number", description: "Put it on a phone line.", icon: <PhoneList weight="duotone" />, status: "pending" },
                ]}
              />
            </Demo>
            <Demo name="Done, active and pending">
              <Stepper
                label="Setup, one done"
                steps={[
                  { title: "Create an agent", description: "Front desk agent is ready.", icon: <Robot weight="duotone" />, status: "done" },
                  {
                    title: "Make a test call",
                    description: "Talk to it from the browser.",
                    icon: <PhoneCallDuo weight="duotone" />,
                    status: "active",
                    action: (
                      <Button size="sm" variant="primary">
                        Make a test call
                      </Button>
                    ),
                  },
                  { title: "Connect a number", description: "Put it on a phone line.", icon: <PhoneList weight="duotone" />, status: "pending" },
                ]}
              />
            </Demo>
          </div>
        </Section>

        <Section
          title="Panels and rows"
          note="One card anatomy: icon, title and one-line description in the header; rows with the icon and label left, the value or control right."
        >
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
            <Panel title="Workspace" description="Name and defaults for new calls." icon={<Gauge />} bodyClassName="p-0">
              <PanelRows>
                <div className="flex items-center justify-between gap-4 px-5 py-4">
                  <span className="flex items-center gap-3 text-[13.5px] font-medium text-fg">
                    <Disc className="size-4 text-fg-3" aria-hidden />
                    Switch, on and off
                  </span>
                  <span className="flex items-center gap-3">
                    <SwitchControl aria-label="Demo switch on" checked onCheckedChange={() => {}} />
                    <SwitchControl aria-label="Demo switch off" checked={false} onCheckedChange={() => {}} />
                    <SwitchControl aria-label="Demo switch disabled" checked disabled onCheckedChange={() => {}} />
                  </span>
                </div>
              </PanelRows>
            </Panel>
            <Panel title="Limits and account" description="Contact support to change these." icon={<Gauge />} bodyClassName="p-0">
              <PanelRows as="dl">
                <InfoRow icon={<Gauge />} label="Concurrent calls">
                  <span className="font-mono tnum">5</span> at once
                </InfoRow>
                <InfoRow icon={<Mail />} label="Account email" title="operations-team+frontdesk@halcyon-dental-group.com">
                  operations-team+frontdesk@halcyon-dental-group.com
                </InfoRow>
              </PanelRows>
            </Panel>
          </div>
        </Section>

        <Section title="Tabs">
          <Tabs
            value={tab}
            onValueChange={setTab}
            items={[
              { value: "one", label: "Transactions", count: 312 },
              { value: "two", label: "Usage" },
              { value: "three", label: "Invoices", disabled: true },
            ]}
          >
            <TabPanel value="one">
              <p className="text-[13.5px] text-fg-2">Arrow keys move between tabs; the marker slides.</p>
            </TabPanel>
            <TabPanel value="two">
              <p className="text-[13.5px] text-fg-2">Second panel.</p>
            </TabPanel>
          </Tabs>
        </Section>

        <Section title="Table and pagination">
          <div className="rounded-panel border border-line bg-surface shadow-1">
            <Table columns={COLS} rows={ROWS} rowKey={(r) => r.id} caption="Sample calls" selectedKey="call_01JA8Z4C9M2R" />
            <div className="border-t border-line">
              <Pagination page={page} totalPages={16} total={312} pageSize={20} onPageChange={setPage} noun="calls" />
            </div>
          </div>
          <div className="mt-4 rounded-panel border border-line bg-surface">
            <Table columns={COLS} rows={undefined} rowKey={(r) => r.id} loading skeletonRows={3} caption="Loading" />
          </div>
        </Section>

        <Section title="Overlays and feedback">
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setDialog(true)}>Open dialog</Button>
            <Button onClick={() => setConfirm(true)}>Confirm dialog</Button>
            <Button onClick={() => setDrawer(true)}>Open drawer</Button>
            <Button onClick={() => toast({ tone: "success", title: "Settings saved" })}>Success toast</Button>
            <Button
              onClick={() =>
                toast({ tone: "error", title: "Settings were not saved", description: "The server did not answer. Try again; reference 4f1c9e0a." })
              }
            >
              Error toast
            </Button>
          </div>
          <Dialog
            open={dialog}
            onOpenChange={setDialog}
            title="Rename agent"
            description="The name shows in call lists and reports."
            footer={
              <>
                <Button onClick={() => setDialog(false)}>Cancel</Button>
                <Button variant="primary" onClick={() => setDialog(false)}>
                  Save name
                </Button>
              </>
            }
          >
            <Field label="Name">{({ id }) => <Input id={id} defaultValue="Front desk" />}</Field>
          </Dialog>
          <ConfirmDialog
            open={confirm}
            onOpenChange={setConfirm}
            title="Leave without saving?"
            description="You have changes that are not saved."
            confirmLabel="Leave"
            cancelLabel="Stay"
            tone="danger"
            onConfirm={() => setConfirm(false)}
          />
          <Drawer open={drawer} onOpenChange={setDrawer} title="Call with +1 (312) 847-1928" meta="14 Oct, 10:42">
            <CostBreakdownCard breakdown={referenceBreakdown} />
          </Drawer>
        </Section>

        <Section title="Empty and loading states">
          <div className="grid gap-5 md:grid-cols-2">
            <div className="rounded-panel border border-dashed border-line-strong px-5">
              <EmptyState
                icon={<FolderOpen weight="duotone" />}
                title="No datasets yet"
                actions={
                  <Button variant="primary" size="sm" icon={<Plus aria-hidden />}>
                    New dataset
                  </Button>
                }
              >
                Save calls into a dataset to replay them against a new prompt.
              </EmptyState>
            </div>
            <div className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-5">
              <Skeleton className="h-5 w-1/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
        </Section>

        <Section
          title="Loading mark"
          note="LogoLoader: the two halves of the Handoff C orbit and pass the turn back and forth, locking into the mark twice a loop. For app boot, route loading and full-page checks; content-shaped loading keeps shimmer skeletons. Reduced motion shows the still mark breathing."
        >
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <Demo name="Small, 24 px (inline)">
              <div className="flex items-center gap-3 text-[13px] text-fg-2">
                <LogoLoader size="sm" />
                Checking your session
              </div>
            </Demo>
            <Demo name="Medium, 40 px">
              <LogoLoader size="md" className="self-center" />
            </Demo>
            <Demo name="Large, 64 px, with label">
              <LogoLoader size="lg" label="Loading billing" className="self-center" />
            </Demo>
            <Demo name="Extra large, 96 px">
              <LogoLoader size="xl" className="self-center" />
            </Demo>
            <Demo name="On the console">
              <div className="grid place-items-center rounded-control bg-console py-6">
                <LogoLoader size="lg" onConsole />
              </div>
            </Demo>
            <Demo name="Reduced motion">
              <LogoLoader size="lg" still label="Still, breathing" className="self-center" />
            </Demo>
          </div>
        </Section>

        <Section title="Receipt">
          <div className="max-w-[480px]">
            <CostBreakdownCard breakdown={referenceBreakdown} />
          </div>
        </Section>
      </main>
    </div>
  );
}

function GalleryComposer() {
  const [value, setValue] = useState("");
  return <Composer label="Gallery composer" value={value} onChange={setValue} onSubmit={() => setValue("")} placeholder="Ask for a change" />;
}
