import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Captions, CircleAlert, CircleCheck, Ear, Mic, MicOff, Phone, PhoneOff, RotateCcw, UserPlus, Volume2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api, unwrap } from "../../../api/client";
import { ApiError } from "../../../api/errors";
import { WAKE_EXPECTED_MS, inlineWake, useWakeState } from "../../../api/wakeGate";
import { Button, FlowChain, LatencyChip, OnAir, Waveform, cn, focusRing, type FlowNode } from "../../../components";
import { RingingPhone, isRinging, useRingback } from "../../../components/ringing";
import { useWebCall } from "../../../components/useWebCall";
import { createMockDriver, type CallProblem, type CallTurn } from "../../../components/webCall";
import { createDemoDriver } from "../../../components/webCallLive";
import { env } from "../../../lib/env";
import { formatUsd } from "../../../lib/money";
import { SEED_PER_MINUTE_MICROS } from "../../../lib/stack";
import { LiveCall } from "../LiveCall";
import { SCENARIOS, type Scenario } from "./scenarios";

/** Demo calls end here even if the agent's own limit is longer. */
const MAX_CALL_MS = 120_000;

const NODES: FlowNode[] = [
  { key: "caller", label: "You", icon: <Mic aria-hidden /> },
  { key: "stt", label: "Speech to text", icon: <Captions aria-hidden /> },
  { key: "llm", label: "Model", icon: <BrainCircuit aria-hidden /> },
  { key: "tts", label: "Voice", icon: <Volume2 aria-hidden /> },
  { key: "hears", label: "You hear", icon: <Ear aria-hidden /> },
];

const mss = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const replyMs = (t: CallTurn) => (t.latency ? t.latency.stt + t.latency.llm + t.latency.tts : null);

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid]! : Math.round((sorted[mid - 1]! + sorted[mid]!) / 2);
}

/** Refusals reworded for a visitor without an account. */
function demoProblem(e: unknown): CallProblem | undefined {
  if (!(e instanceof ApiError)) return undefined;
  if (e.status === 429)
    return {
      kind: "refused",
      title: "That's all the demo calls for this hour",
      detail: "Create an account to keep calling. New workspaces start with $5 of calls.",
      action: { label: "Create account", href: "/register" },
    };
  if (e.status === 402 || e.status === 404 || e.status === 409)
    return {
      kind: "refused",
      title: "The demo line is closed right now",
      detail: "Create an account to call an agent of your own. New workspaces start with $5 of calls.",
      action: { label: "Create account", href: "/register" },
    };
  return undefined;
}

/**
 * Home hero: the sample console becomes a real call. Visitors pick a scenario, get a part to play
 * and call the demo agent from the browser (POST /v1/public/demo-calls). The console shows what
 * the product measures: every agent reply's latency split by link of the chain, the running cost
 * and the link that is working. When the API has no demo agents the sample call plays instead.
 */
export function Playground({ className }: { className?: string }) {
  const demo = useQuery({
    queryKey: ["public", "demo"],
    queryFn: () => unwrap(api.GET("/public/demo")),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const scenarios = useMemo(() => SCENARIOS.filter((s) => demo.data?.agents.includes(s.key)), [demo.data]);

  if (demo.isPending) return <ConsoleFrame className={className} />;
  if (scenarios.length === 0) return <LiveCall className={className} />;
  return <PlaygroundConsole scenarios={scenarios} className={className} />;
}

function ConsoleFrame({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <div id="playground" className={cn("relative scroll-mt-24", className)}>
      <section
        aria-label="Try a call"
        className="relative flex min-h-[500px] flex-col overflow-hidden rounded-feature border border-console-line bg-console text-console-fg shadow-2"
      >
        {children}
      </section>
    </div>
  );
}

function PlaygroundConsole({ scenarios, className }: { scenarios: Scenario[]; className?: string }) {
  const reduce = useReducedMotion() ?? false;
  const [key, setKey] = useState(scenarios[0]!.key);
  const scenario = scenarios.find((s) => s.key === key) ?? scenarios[0]!;
  const driver = useMemo(() => (env.mocks ? createMockDriver() : createDemoDriver(scenario.key)), [scenario.key]);
  const request = useMemo(() => ({ agent_id: scenario.key }), [scenario.key]);
  const { state: s, start, cancel, end, toggleMute, elapsed } = useWebCall(driver, request, undefined, demoProblem);
  const wake = useWakeState();

  // This console shows the server wake-up itself, so the full-page overlay stays away.
  useEffect(() => inlineWake.claim(), []);

  const onCall = s.phase === "live" || s.phase === "ending";
  const busy = s.phase === "checking" || s.phase === "requesting" || s.phase === "connecting";
  const waking = s.phase === "requesting" && wake.status === "waking";
  const ringing = isRinging(s);
  useRingback(ringing);

  useEffect(() => {
    if (s.phase === "live" && elapsed >= MAX_CALL_MS) void end();
  }, [s.phase, elapsed, end]);

  const costMicros = (SEED_PER_MINUTE_MICROS * BigInt(Math.max(0, Math.round(elapsed)))) / 60_000n;
  const link = !onCall
    ? null
    : s.activity === "speaking"
      ? "tts"
      : s.activity === "thinking"
        ? "llm"
        : s.levels.caller > 0.08 && !s.muted
          ? "caller"
          : null;

  const pick = (next: string) => {
    if (busy || onCall || next === key) return;
    cancel();
    setKey(next);
  };

  // The home template rail's "Try it now" switches the scenario from outside.
  const pickRef = useRef(pick);
  pickRef.current = pick;
  useEffect(() => {
    const onTry = (e: Event) => {
      const next = (e as CustomEvent<string>).detail;
      if (scenarios.some((sc) => sc.key === next)) pickRef.current(next);
    };
    window.addEventListener("cw:playground", onTry);
    return () => window.removeEventListener("cw:playground", onTry);
  }, [scenarios]);

  return (
    <ConsoleFrame className={className}>
      {s.phase !== "idle" && (
        <header className="flex items-center justify-between gap-4 border-b border-console-line px-5 py-2.5">
          <HeaderStatus phase={s.phase} waking={waking} ringing={ringing} />
          <dl className="flex items-center gap-4 whitespace-nowrap text-[12px] text-console-fg-2">
            <div className="flex items-center gap-1.5">
              <dt className="sr-only">Duration</dt>
              <dd className="font-mono text-console-fg tnum">
                {mss(elapsed)}
                <span className="text-console-fg-2"> / {mss(MAX_CALL_MS)}</span>
              </dd>
            </div>
            <div className="flex items-center gap-1.5">
              <dt className="max-sm:sr-only">Cost so far</dt>
              <dd className="w-[62px] text-right font-mono text-console-fg tnum">{formatUsd(costMicros, { places: 4 })}</dd>
            </div>
          </dl>
        </header>
      )}

      {!onCall && !busy && (
        <div
          role="radiogroup"
          aria-label="Scenario"
          className="flex gap-1 overflow-x-auto px-5 pt-5 [mask-image:linear-gradient(to_right,black_80%,transparent)] [scrollbar-width:none] sm:[mask-image:none] [&::-webkit-scrollbar]:hidden"
        >
          {scenarios.map((sc) => {
            const selected = sc.key === scenario.key;
            return (
              <button
                key={sc.key}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => pick(sc.key)}
                className={cn(
                  "relative flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors duration-150",
                  selected ? "text-console-fg" : "text-console-fg-2 hover:text-console-fg",
                  focusRing,
                )}
              >
                {selected && (
                  <motion.span
                    layoutId="scenario-pill"
                    aria-hidden
                    className="absolute inset-0 rounded-full border border-console-line bg-console-2"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  />
                )}
                <sc.icon className={cn("relative size-3.5", selected && "text-[#b9b2ff]")} aria-hidden />
                <span className="relative">{sc.label}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="relative grid min-h-0 flex-1 px-5 py-5">
        <AnimatePresence mode="wait" initial={false}>
          {s.phase === "error" && s.problem ? (
            <Fade key="error">
              <Problem problem={s.problem} />
            </Fade>
          ) : waking ? (
            <Fade key="waking">
              <Waking startedAt={wake.status === "waking" ? wake.startedAt : Date.now()} />
            </Fade>
          ) : ringing ? (
            <Fade key="ringing" className="grid h-full place-items-center content-center gap-4 text-center">
              <RingingPhone reduce={reduce} onConsole />
              <p className="text-[14px] font-medium text-console-fg-2" role="status">
                Ringing the agent
              </p>
            </Fade>
          ) : onCall || (s.phase === "connecting" && s.turns.length > 0) ? (
            <Fade key="live" className="flex h-full flex-col gap-3">
              <Waveform bars={64} seed={11} progress={1} live={onCall} onConsole height={26} flat={!onCall} />
              <Transcript turns={s.turns} reduce={reduce} />
            </Fade>
          ) : s.phase === "ended" ? (
            <Fade key="ended">
              <Summary turns={s.turns} elapsed={elapsed} costMicros={costMicros} agentEnded={s.endReason === "agent_hangup"} />
            </Fade>
          ) : (
            <Fade key={`brief-${scenario.key}`}>
              <Brief scenario={scenario} dim={busy} />
            </Fade>
          )}
        </AnimatePresence>
      </div>

      <footer className={cn("flex flex-col gap-4 px-5 pb-5", onCall ? "border-t border-console-line pt-3.5" : "pt-1")}>
        {onCall && <FlowChain nodes={NODES} active={link} flow onConsole size="sm" stack="never" />}
        <div className="flex flex-wrap-reverse items-center justify-between gap-x-4 gap-y-3">
          <p className="min-w-0 flex-1 basis-48 text-[13px] leading-snug text-console-fg-2">
            {onCall
              ? s.muted
                ? "Your microphone is muted."
                : "Talk normally. Interrupt the agent if you like; it stops and listens."
              : "Uses your microphone. No account needed, ends after 2 minutes."}
          </p>
          <div className="flex items-center gap-2">
            {onCall && (
              <button
                type="button"
                aria-label={s.muted ? "Unmute microphone" : "Mute microphone"}
                aria-pressed={s.muted}
                onClick={toggleMute}
                disabled={s.phase === "ending"}
                className={cn(
                  "grid size-10 cursor-pointer place-items-center rounded-full border transition-colors",
                  s.muted ? "border-transparent bg-[#ffb347] text-[#2b1600]" : "border-console-line text-console-fg-2 hover:text-console-fg",
                  focusRing,
                )}
              >
                {s.muted ? <MicOff className="size-4" aria-hidden /> : <Mic className="size-4" aria-hidden />}
              </button>
            )}
            {onCall ? (
              <Button variant="danger" size="lg" icon={<PhoneOff aria-hidden />} pending={s.phase === "ending"} onClick={() => void end()}>
                Hang up
              </Button>
            ) : busy ? (
              <>
                {s.phase === "connecting" ? (
                  <Button variant="danger" size="lg" icon={<PhoneOff aria-hidden />} onClick={cancel}>
                    Hang up
                  </Button>
                ) : (
                  <Button variant="primary" size="lg" pending>
                    {s.phase === "checking" ? "Allow the microphone" : waking ? "Starting servers" : "Connecting"}
                  </Button>
                )}
              </>
            ) : s.phase === "ended" ? (
              // The summary's "Build your own agent" is the main action after a call.
              <button
                type="button"
                onClick={() => void start()}
                className={cn(
                  "inline-flex h-11 cursor-pointer items-center gap-2 rounded-control border border-console-line px-4 text-[14px] font-medium text-console-fg transition-colors hover:bg-console-2",
                  focusRing,
                )}
              >
                <RotateCcw className="size-4" aria-hidden />
                Call again
              </button>
            ) : (
              <Button variant="primary" size="lg" icon={<Phone aria-hidden />} onClick={() => void start()}>
                {s.phase === "idle" ? scenario.action : "Try again"}
              </Button>
            )}
          </div>
        </div>
      </footer>
    </ConsoleFrame>
  );
}

function Fade({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
      className={cn("h-full", className)}
    >
      {children}
    </motion.div>
  );
}

function HeaderStatus({ phase, waking, ringing }: { phase: string; waking: boolean; ringing: boolean }) {
  if (ringing)
    return (
      <span className="inline-flex items-center gap-2 whitespace-nowrap text-[13px] font-medium text-console-fg">
        <Phone className="size-4" aria-hidden />
        Ringing
      </span>
    );
  if (phase === "live" || phase === "ending") return <OnAir label="Live call" onConsole />;
  if (phase === "ended")
    return (
      <span className="inline-flex items-center gap-2 whitespace-nowrap text-[13px] font-medium text-console-fg-2">
        <CircleCheck className="size-4 text-[#5fd3a4]" aria-hidden />
        Call ended
      </span>
    );
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap text-[13px] font-medium text-console-fg-2">
      <Phone className="size-4" aria-hidden />
      {waking ? "Starting the call servers" : phase === "idle" || phase === "error" ? "Try a real call" : "Connecting"}
    </span>
  );
}

function Brief({ scenario, dim }: { scenario: Scenario; dim: boolean }) {
  return (
    <div className={cn("flex h-full flex-col justify-center gap-6 transition-opacity duration-200", dim && "opacity-60")}>
      <p className="max-w-[34ch] text-[20px] leading-[1.5] tracking-[-0.01em] text-console-fg sm:text-[22px]">{scenario.brief}</p>
      <div className="text-[14px] leading-relaxed text-console-fg-2">
        <p>Try saying</p>
        <ul className="mt-1">
          {scenario.lines.map((line) => (
            <li key={line} className="text-console-fg/80">
              &ldquo;{line}&rdquo;
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Waking({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  const progress = Math.min(0.95, (now - startedAt) / WAKE_EXPECTED_MS);
  return (
    <div className="flex h-full flex-col justify-center gap-4" role="status">
      <p className="max-w-[42ch] text-[15px] leading-relaxed text-console-fg">
        Starting the call servers. They sleep when nobody is calling, so the first call takes about a minute.
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-console-2" aria-hidden>
        <motion.div
          className="h-full rounded-full bg-[linear-gradient(90deg,var(--heat-1),var(--heat-2)_60%,var(--heat-3))]"
          animate={{ width: `${Math.round(progress * 100)}%` }}
          transition={{ duration: 0.5, ease: "linear" }}
        />
      </div>
      <p className="text-[13px] text-console-fg-2">The call starts on its own once they answer. Nothing is charged before it connects.</p>
    </div>
  );
}

const Transcript = memo(function Transcript({ turns, reduce }: { turns: CallTurn[]; reduce: boolean }) {
  const ref = useRef<HTMLOListElement>(null);
  const last = turns[turns.length - 1];
  useEffect(() => {
    ref.current?.scrollTo?.({ top: ref.current.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [turns.length, last?.text, last?.latency, reduce]);
  if (turns.length === 0)
    return (
      <p className="grid flex-1 place-items-center text-center text-[13px] text-console-fg-2">The agent is picking up. Say hello once it speaks.</p>
    );
  return (
    <ol
      ref={ref}
      aria-label="Transcript"
      aria-live="polite"
      className="flex max-h-[260px] min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain pr-1 pt-2 [mask-image:linear-gradient(to_bottom,transparent,black_20px)]"
    >
      {turns.map((t) => {
        const agent = t.who === "agent";
        return (
          <motion.li
            key={t.id}
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            className={cn("flex flex-col gap-1", agent ? "items-start" : "items-end text-right")}
          >
            <p
              className={cn(
                "max-w-[40ch] rounded-panel px-3 py-1.5 text-[14px] leading-snug",
                agent ? "rounded-bl-[4px] bg-[#2a33a8] text-white" : "rounded-br-[4px] bg-console-2 text-console-fg",
                !t.final && "opacity-75",
              )}
            >
              {t.text}
            </p>
            {agent && t.latency && <LatencyChip latency={t.latency} onConsole />}
          </motion.li>
        );
      })}
    </ol>
  );
});

function Summary({ turns, elapsed, costMicros, agentEnded }: { turns: CallTurn[]; elapsed: number; costMicros: bigint; agentEnded: boolean }) {
  const replies = turns.filter((t) => t.who === "agent" && t.final);
  const med = median(replies.map(replyMs).filter((v): v is number => v !== null));
  const stats = [
    { label: "Length", value: mss(elapsed) },
    { label: "Agent replies", value: String(replies.length) },
    { label: "Typical reply time", value: med === null ? "n/a" : `${med} ms` },
    { label: "Cost", value: formatUsd(costMicros, { places: 4 }) },
  ];
  return (
    <div className="flex h-full flex-col gap-5">
      <p className="max-w-[44ch] text-[16px] leading-relaxed text-console-fg">
        {agentEnded ? "The agent wrapped up and hung up." : "You hung up."} This is what Callwright records for every call, with the transcript,
        recording and an itemised bill.
      </p>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-panel border border-console-line bg-console-line">
        {stats.map((x) => (
          <div key={x.label} className="flex flex-col gap-1 bg-console px-4 py-3">
            <dt className="text-[12px] text-console-fg-2">{x.label}</dt>
            <dd className="font-mono text-[18px] text-console-fg tnum">{x.value}</dd>
          </div>
        ))}
      </dl>
      <Button asChild variant="primary" icon={<UserPlus aria-hidden />} className="mt-auto self-start">
        <Link to="/register">Build your own agent</Link>
      </Button>
    </div>
  );
}

function Problem({ problem }: { problem: CallProblem }) {
  const mic = problem.kind === "mic_denied" || problem.kind === "mic_unavailable";
  return (
    <div role="alert" className="flex h-full flex-col gap-3">
      <p className="flex items-center gap-2 text-[15px] font-semibold text-console-fg">
        {mic ? <MicOff className="size-[18px] text-[#ffb347]" aria-hidden /> : <CircleAlert className="size-[18px] text-[#ff8fa3]" aria-hidden />}
        {problem.title}
      </p>
      <p className="max-w-[46ch] text-[14px] leading-relaxed text-console-fg-2">{problem.detail}</p>
      {problem.action && (
        <Button asChild variant="primary" icon={<UserPlus aria-hidden />} className="mt-2 self-start">
          <Link to={problem.action.href}>{problem.action.label}</Link>
        </Button>
      )}
    </div>
  );
}
