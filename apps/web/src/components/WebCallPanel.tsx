/**
 * Shared browser test-call panel (spec 003 US1, FR-047, research R17). Used by the agent testing
 * page and embedded by the agent editor.
 *
 * Order of operations is fixed: microphone check, then `POST /v1/sessions/web-call`, then the
 * room. A blocked microphone stops at step one, so no call is created or charged.
 *
 * Shows the on-air state, a live waveform for each side, the live transcript with a latency chip
 * on every agent turn, the running duration and estimated cost, mute, end call, and a clear error
 * state. In mock mode (`mode="mock"`, the default when the app runs on MSW mocks) a scripted call
 * plays on timers, so the panel works in the gallery and tests without LiveKit.
 */
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { CircleAlert, CircleCheck, Mic, MicOff, Phone, PhoneCall, PhoneOff, TriangleAlert } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { env } from "../lib/env";
import { formatUsd } from "../lib/money";
import { SEED_PER_MINUTE_MICROS } from "../lib/stack";
import { Badge } from "./Badge";
import { Button, IconButton } from "./Button";
import { cn } from "./cn";
import { EASE_OUT } from "./motion";
import { LatencyChip, OnAir, Waveform, type Latency } from "./signal";
import { InfoTip } from "./TruncatedText";
import {
  CONNECTION_FAILED,
  MIC_DENIED,
  MIC_UNAVAILABLE,
  createMockDriver,
  problemFromError,
  type AgentActivity,
  type CallConnection,
  type CallLevels,
  type CallListener,
  type CallProblem,
  type CallTurn,
  type EndReason,
  type MockOptions,
  type WebCallDriver,
} from "./webCall";
import { createLiveDriver } from "./webCallLive";

export type CallPhase = "idle" | "checking" | "requesting" | "connecting" | "live" | "ending" | "ended" | "error";

export interface CallSummary {
  callId: string | null;
  durationMs: number;
  reason: EndReason;
}

export interface WebCallPanelProps {
  agentId: string;
  /** `draft` (default), `published` or an `agv_` id. */
  version?: string;
  variables?: Record<string, string>;
  /** Per-minute price of the agent's stack, for the running cost estimate. */
  perMinuteMicros?: bigint;
  /** `mock` plays a scripted call on timers. Defaults to `mock` when the app runs on MSW mocks. */
  mode?: "live" | "mock";
  mockOptions?: MockOptions;
  /** Overrides `mode` (tests). */
  driver?: WebCallDriver;
  onEnded?: (summary: CallSummary) => void;
  className?: string;
}

interface State {
  phase: CallPhase;
  activity: AgentActivity;
  turns: CallTurn[];
  levels: CallLevels;
  muted: boolean;
  callId: string | null;
  startedAt: number | null;
  endedAt: number | null;
  endReason: EndReason | null;
  problem: CallProblem | null;
}

type Action =
  | { type: "checking" }
  | { type: "requesting" }
  | { type: "connecting"; callId: string }
  | { type: "live"; at: number }
  | { type: "activity"; activity: AgentActivity }
  | { type: "turn"; turn: CallTurn }
  | { type: "latency"; turnId: string | null; latency: Latency }
  | { type: "levels"; levels: CallLevels }
  | { type: "muted"; muted: boolean }
  | { type: "ending" }
  | { type: "ended"; reason: EndReason; at: number }
  | { type: "fail"; problem: CallProblem }
  | { type: "reset" };

const SILENT: CallLevels = { caller: 0, agent: 0 };

const INITIAL: State = {
  phase: "idle",
  activity: "joining",
  turns: [],
  levels: SILENT,
  muted: false,
  callId: null,
  startedAt: null,
  endedAt: null,
  endReason: null,
  problem: null,
};

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "checking":
      return { ...INITIAL, phase: "checking" };
    case "requesting":
      return { ...s, phase: "requesting" };
    case "connecting":
      return { ...s, phase: "connecting", callId: a.callId };
    case "live":
      return s.phase === "connecting" ? { ...s, phase: "live", startedAt: a.at } : s;
    case "activity":
      return { ...s, activity: a.activity };
    case "turn": {
      const i = s.turns.findIndex((t) => t.id === a.turn.id);
      if (i < 0) return { ...s, turns: [...s.turns, a.turn] };
      const turns = s.turns.slice();
      const prev = turns[i]!;
      turns[i] = { ...prev, ...a.turn, latency: a.turn.latency ?? prev.latency };
      return { ...s, turns };
    }
    case "latency": {
      let i = a.turnId ? s.turns.findIndex((t) => t.id === a.turnId) : -1;
      if (i < 0) i = s.turns.findLastIndex((t) => t.who === "agent");
      if (i < 0) return s;
      const turns = s.turns.slice();
      turns[i] = { ...turns[i]!, latency: a.latency };
      return { ...s, turns };
    }
    case "levels":
      return s.phase === "live" || s.phase === "ending" ? { ...s, levels: a.levels } : s;
    case "muted":
      return { ...s, muted: a.muted };
    case "ending":
      return { ...s, phase: "ending" };
    case "ended":
      if (s.phase === "ended") return s;
      return { ...s, phase: "ended", endReason: a.reason, endedAt: a.at, levels: SILENT, muted: false };
    case "fail":
      return { ...s, phase: "error", problem: a.problem, levels: SILENT };
    case "reset":
      return INITIAL;
  }
}

const mss = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function newIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `wc-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export function WebCallPanel({
  agentId,
  version,
  variables,
  perMinuteMicros = SEED_PER_MINUTE_MICROS,
  mode = env.mocks ? "mock" : "live",
  mockOptions,
  driver: driverProp,
  onEnded,
  className,
}: WebCallPanelProps) {
  const driver = useMemo(() => driverProp ?? (mode === "mock" ? createMockDriver(mockOptions) : createLiveDriver()), [driverProp, mode, mockOptions]);
  const [s, dispatch] = useReducer(reducer, INITIAL);
  const reduce = useReducedMotion() ?? false;
  const run = useRef(0);
  const conn = useRef<CallConnection | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;

  // Clock for duration and cost while the call runs.
  useEffect(() => {
    if (s.phase !== "live" && s.phase !== "ending") return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [s.phase]);

  // Report the end once.
  const reported = useRef<number | null>(null);
  useEffect(() => {
    if (s.phase !== "ended" || s.endReason === null || reported.current === s.endedAt) return;
    reported.current = s.endedAt;
    onEndedRef.current?.({ callId: s.callId, durationMs: s.startedAt && s.endedAt ? s.endedAt - s.startedAt : 0, reason: s.endReason });
  }, [s.phase, s.endReason, s.endedAt, s.startedAt, s.callId]);

  // Leaving the page hangs up (US1.5: closing the tab ends the call server side as user_hangup).
  useEffect(
    () => () => {
      run.current += 1;
      void conn.current?.hangUp().catch(() => {});
      conn.current = null;
    },
    [],
  );

  const start = useCallback(async () => {
    const id = ++run.current;
    const stale = () => id !== run.current;
    dispatch({ type: "checking" });
    const mic = await driver.checkMicrophone().catch(() => "unavailable" as const);
    if (stale()) return;
    if (mic !== "granted") {
      dispatch({ type: "fail", problem: mic === "denied" ? MIC_DENIED : MIC_UNAVAILABLE });
      return;
    }
    dispatch({ type: "requesting" });
    let session;
    try {
      session = await driver.createSession(
        { agent_id: agentId, ...(version && { version }), ...(variables && { dynamic_variables: variables }) },
        newIdempotencyKey(),
      );
    } catch (e) {
      if (!stale()) dispatch({ type: "fail", problem: problemFromError(e) });
      return;
    }
    if (stale()) return;
    dispatch({ type: "connecting", callId: session.call_id });
    const listener: CallListener = {
      activity: (activity) => !stale() && dispatch({ type: "activity", activity }),
      turn: (turn) => !stale() && dispatch({ type: "turn", turn }),
      latency: (turnId, latency) => !stale() && dispatch({ type: "latency", turnId, latency }),
      levels: (levels) => !stale() && dispatch({ type: "levels", levels }),
      ended: (reason) => {
        if (stale()) return;
        conn.current = null;
        dispatch({ type: "ended", reason, at: Date.now() });
      },
    };
    let c: CallConnection;
    try {
      c = await driver.connect(session, listener);
    } catch {
      if (!stale()) dispatch({ type: "fail", problem: CONNECTION_FAILED });
      return;
    }
    if (stale()) {
      void c.hangUp().catch(() => {});
      return;
    }
    conn.current = c;
    dispatch({ type: "live", at: Date.now() });
  }, [driver, agentId, version, variables]);

  const cancel = useCallback(() => {
    run.current += 1;
    dispatch({ type: "reset" });
  }, []);

  const end = useCallback(async () => {
    const c = conn.current;
    dispatch({ type: "ending" });
    try {
      await c?.hangUp();
    } finally {
      dispatch({ type: "ended", reason: "user_hangup", at: Date.now() });
    }
  }, []);

  const toggleMute = useCallback(() => {
    const next = !s.muted;
    dispatch({ type: "muted", muted: next });
    void conn.current?.setMuted(next).catch(() => dispatch({ type: "muted", muted: !next }));
  }, [s.muted]);

  const elapsed = s.startedAt ? (s.endedAt ?? now) - s.startedAt : 0;
  const costMicros = (perMinuteMicros * BigInt(Math.max(0, Math.round(elapsed)))) / 60_000n;
  const onCall = s.phase === "live" || s.phase === "ending";
  const lastFinal = [...s.turns].reverse().find((t) => t.final);

  return (
    <section
      aria-label="Test call"
      data-phase={s.phase}
      className={cn("flex min-w-0 flex-col overflow-hidden rounded-feature border border-line bg-surface shadow-2", className)}
    >
      <header className="flex min-h-14 items-center justify-between gap-3 border-b border-line px-5 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <Status phase={s.phase} reason={s.endReason} reduce={reduce} />
          {driver.simulated && <Badge>Simulated</Badge>}
        </div>
        <dl className="flex shrink-0 items-center gap-4 text-[12px] text-fg-3">
          <div className="flex items-center">
            <dt className="sr-only">Duration</dt>
            <dd className="w-10 text-right font-mono text-[13px] text-fg tnum">{mss(elapsed)}</dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt>Cost</dt>
            <dd className="w-[60px] text-right font-mono text-[13px] text-fg tnum">{formatUsd(costMicros, { places: 4 })}</dd>
            <InfoTip label="How the cost is estimated" side="bottom">
              Estimated from the stack's per-minute price while the call runs. The exact charge is settled once the call is processed. Billing starts
              when the call connects.
            </InfoTip>
          </div>
        </dl>
      </header>

      <div className="grid gap-2 px-5 pt-4">
        <WaveRow
          label="Agent"
          status={agentStatus(s.phase, s.activity)}
          level={s.levels.agent}
          active={onCall && s.activity === "speaking"}
          idle={!onCall}
          seed={11}
          reduce={reduce}
        />
        <WaveRow
          label="You"
          status={callerStatus(s.phase, s.muted, s.levels.caller)}
          level={s.muted ? 0 : s.levels.caller}
          active={onCall && !s.muted && s.levels.caller > 0.08}
          muted={onCall && s.muted}
          idle={!onCall}
          seed={5}
          reduce={reduce}
        />
      </div>

      <div className="relative mx-5 my-4 h-72 min-h-0">
        {s.phase === "error" && s.problem ? (
          <ProblemCallout problem={s.problem} />
        ) : s.turns.length === 0 ? (
          <EmptyTranscript phase={s.phase} />
        ) : (
          <Transcript turns={s.turns} reduce={reduce} />
        )}
      </div>
      <p className="sr-only" aria-live="polite">
        {lastFinal ? `${lastFinal.who === "agent" ? "Agent" : "You"}: ${lastFinal.text}` : ""}
      </p>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
        <p className="min-w-0 flex-1 basis-56 text-[12.5px] text-fg-3">{footerHint(s, elapsed, costMicros)}</p>
        <div className="flex items-center gap-2">
          {(s.phase === "idle" || s.phase === "ended" || s.phase === "error") && (
            <Button variant="primary" icon={<Phone aria-hidden />} onClick={() => void start()}>
              {s.phase === "idle" ? "Start test call" : s.phase === "ended" ? "Call again" : "Try again"}
            </Button>
          )}
          {(s.phase === "checking" || s.phase === "requesting") && (
            <Button variant="primary" pending>
              {s.phase === "checking" ? "Checking microphone" : "Starting call"}
            </Button>
          )}
          {s.phase === "connecting" && (
            <>
              <Button variant="ghost" onClick={cancel}>
                Cancel
              </Button>
              <Button variant="primary" pending>
                Connecting
              </Button>
            </>
          )}
          {onCall && (
            <>
              <IconButton
                label={s.muted ? "Unmute microphone" : "Mute microphone"}
                aria-pressed={s.muted}
                onClick={toggleMute}
                disabled={s.phase === "ending"}
                className={cn(
                  "border border-line-strong",
                  s.muted && "border-transparent bg-warning-soft text-warning-text hover:bg-warning-soft hover:text-warning-text",
                )}
              >
                {s.muted ? <MicOff aria-hidden /> : <Mic aria-hidden />}
              </IconButton>
              <Button variant="danger" icon={<PhoneOff aria-hidden />} pending={s.phase === "ending"} onClick={() => void end()}>
                End call
              </Button>
            </>
          )}
        </div>
      </footer>
    </section>
  );
}

function footerHint(s: State, elapsed: number, cost: bigint): string {
  switch (s.phase) {
    case "idle":
      return "Your microphone is checked first. Nothing is charged until the call connects.";
    case "checking":
      return "Allow the microphone if your browser asks.";
    case "requesting":
      return "Checking credit and starting the agent.";
    case "connecting":
      return "Joining the call room.";
    case "live":
    case "ending":
      return s.muted ? "Muted: the agent cannot hear you." : "Talk as the caller. The agent hears your microphone.";
    case "ended":
      return `Ended after ${mss(elapsed)}, about ${formatUsd(cost, { places: 4 })}.`;
    case "error":
      return s.problem?.kind === "connection" ? "The call was not connected, so it was not charged." : "Fix the cause above, then try again.";
  }
}

function agentStatus(phase: CallPhase, activity: AgentActivity): string {
  if (phase === "live" || phase === "ending")
    return { joining: "Joining", listening: "Listening", thinking: "Thinking", speaking: "Speaking" }[activity];
  if (phase === "connecting") return "Joining";
  return phase === "ended" ? "Off call" : "Not connected";
}

function callerStatus(phase: CallPhase, muted: boolean, level: number): string {
  if (phase === "live" || phase === "ending") return muted ? "Muted" : level > 0.08 ? "Speaking" : "Mic on";
  return phase === "ended" ? "Off call" : "Mic off";
}

function Status({ phase, reason, reduce }: { phase: CallPhase; reason: EndReason | null; reduce: boolean }) {
  let node: ReactNode;
  if (phase === "live" || phase === "ending") node = <OnAir label="On air" />;
  else if (phase === "ended")
    node =
      reason === "connection_lost" ? (
        <StatusText icon={<TriangleAlert className="text-warning-text" />} text="Call dropped" />
      ) : (
        <StatusText icon={<CircleCheck className="text-success-text" />} text={reason === "agent_hangup" ? "Agent ended the call" : "Call ended"} />
      );
  else if (phase === "error") node = <StatusText icon={<CircleAlert className="text-danger-text" />} text="Call not started" />;
  else
    node = (
      <StatusText
        icon={<PhoneCall className="text-fg-3" />}
        text={{ idle: "Test call", checking: "Checking microphone", requesting: "Starting call", connecting: "Connecting" }[phase]}
      />
    );
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={phase === "ending" ? "live" : phase}
        initial={reduce ? false : { opacity: 0, y: 3 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduce ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, y: -3 }}
        transition={{ duration: 0.16, ease: EASE_OUT }}
        className="flex min-w-0 items-center"
        role="status"
      >
        {node}
      </motion.span>
    </AnimatePresence>
  );
}

function StatusText({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-[13px] font-medium text-fg [&_svg]:size-4 [&_svg]:shrink-0">
      <span aria-hidden className="inline-flex">
        {icon}
      </span>
      <span className="truncate">{text}</span>
    </span>
  );
}

/**
 * One side's live waveform: the heat ramp while that side speaks, the quiet line otherwise, and a
 * vertical scale that follows the audio level. Reduced motion keeps the bars still and only
 * switches between the two states.
 */
function WaveRow({
  label,
  status,
  level,
  active,
  muted = false,
  idle = false,
  seed,
  reduce,
}: {
  label: string;
  status: string;
  level: number;
  active: boolean;
  muted?: boolean;
  idle?: boolean;
  seed: number;
  reduce: boolean;
}) {
  const scale = reduce ? (active ? 1 : 0.35) : active ? 0.3 + 0.7 * Math.min(1, level * 1.4) : 0.22;
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-3 rounded-control bg-surface-2 py-2 pl-3 pr-3">
      <div className="flex min-w-0 flex-col leading-tight">
        <span className="text-[12.5px] font-medium text-fg">{label}</span>
        <span className={cn("text-[11.5px]", muted ? "text-warning-text" : active ? "text-accent-text" : "text-fg-3")}>{status}</span>
      </div>
      <div
        aria-hidden
        className={cn("h-8 origin-center", !reduce && "transition-transform duration-150 ease-out")}
        style={{ transform: `scaleY(${scale})` }}
      >
        <Waveform bars={56} seed={seed} progress={active ? 1 : 0} live={active} height={32} flat={muted || idle} />
      </div>
    </div>
  );
}

function EmptyTranscript({ phase }: { phase: CallPhase }) {
  const text =
    phase === "idle"
      ? "Start a test call to talk to this agent. The transcript and the latency of every agent reply appear here."
      : phase === "ended"
        ? "Nobody spoke on this call."
        : "The transcript appears here as you and the agent talk.";
  return (
    <div className="grid h-full place-items-center rounded-panel border border-dashed border-line px-6 text-center">
      <p className="max-w-[38ch] text-[13px] leading-relaxed text-fg-3">{text}</p>
    </div>
  );
}

function ProblemCallout({ problem }: { problem: CallProblem }) {
  const mic = problem.kind === "mic_denied" || problem.kind === "mic_unavailable";
  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: EASE_OUT }}
      className={cn("flex gap-3 rounded-panel border p-4", mic ? "border-warning/30 bg-warning-soft" : "border-danger/30 bg-danger-soft")}
    >
      <span aria-hidden className={cn("mt-0.5 [&_svg]:size-[18px]", mic ? "text-warning-text" : "text-danger-text")}>
        {mic ? <MicOff /> : <CircleAlert />}
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-[13.5px] font-semibold text-fg">{problem.title}</p>
        <p className="text-[13px] leading-relaxed text-fg-2">{problem.detail}</p>
        {problem.action && (
          <Link to={problem.action.href} className="link-underline mt-1 self-start text-[13px] font-medium text-accent-text">
            {problem.action.label}
          </Link>
        )}
      </div>
    </motion.div>
  );
}

const Transcript = memo(function Transcript({ turns, reduce }: { turns: CallTurn[]; reduce: boolean }) {
  const ref = useRef<HTMLOListElement>(null);
  const last = turns[turns.length - 1];
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTo?.({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [turns.length, last?.text, last?.latency, reduce]);
  return (
    <ol
      ref={ref}
      aria-label="Transcript"
      className="flex h-full flex-col gap-3 overflow-y-auto overscroll-contain pr-1 pt-3 [mask-image:linear-gradient(to_bottom,transparent,black_28px)]"
    >
      {turns.map((t) => (
        <motion.li
          key={t.id}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.24, ease: EASE_OUT }}
          className={cn("flex flex-col gap-1", t.who === "agent" ? "items-end text-right" : "items-start")}
        >
          <span className="text-[11.5px] font-medium text-fg-3">{t.who === "agent" ? "Agent" : "You"}</span>
          <p
            className={cn(
              "max-w-[40ch] rounded-panel px-3 py-1.5 text-left text-[13px] leading-snug transition-colors duration-200",
              t.who === "agent" ? "rounded-br-[4px] bg-accent-soft" : "rounded-bl-[4px] bg-surface-2",
              t.final ? "text-fg" : "text-fg-2",
            )}
          >
            {t.text}
          </p>
          {t.latency && <LatencyChip latency={t.latency} />}
        </motion.li>
      ))}
    </ol>
  );
});
