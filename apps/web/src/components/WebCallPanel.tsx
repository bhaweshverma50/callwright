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
import { Bot, CircleAlert, CircleCheck, Grid3x3, Mic, MicOff, Phone, PhoneCall, PhoneOff, TriangleAlert, User } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { env } from "../lib/env";
import { formatUsd } from "../lib/money";
import { SEED_PER_MINUTE_MICROS } from "../lib/stack";
import { Badge } from "./Badge";
import { Button, IconButton } from "./Button";
import { cn } from "./cn";
import { EASE_OUT } from "./motion";
import { LatencyChip, OnAir, Waveform } from "./signal";
import { Keypad } from "./Keypad";
import { InfoTip } from "./TruncatedText";
import {
  createMockDriver,
  type AgentActivity,
  type CallProblem,
  type CallTurn,
  type EndReason,
  type MockOptions,
  type WebCallDriver,
} from "./webCall";
import { createLiveDriver } from "./webCallLive";
import { useWebCall, type CallPhase, type CallSummary, type WebCallState } from "./useWebCall";

export type { CallPhase, CallSummary } from "./useWebCall";

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

const mss = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

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
  const request = useMemo(
    () => ({ agent_id: agentId, ...(version && { version }), ...(variables && { dynamic_variables: variables }) }),
    [agentId, version, variables],
  );
  const { state: s, start, cancel, end, toggleMute, sendDigit, elapsed } = useWebCall(driver, request, onEnded);
  const [keypadOpen, setKeypadOpen] = useState(false);
  const reduce = useReducedMotion() ?? false;
  const costMicros = (perMinuteMicros * BigInt(Math.max(0, Math.round(elapsed)))) / 60_000n;
  const onCall = s.phase === "live" || s.phase === "ending";
  const showKeypad = keypadOpen && onCall;
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

      <div className="grid gap-2 px-5 pt-4 sm:grid-cols-2">
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

      <div className={cn("mx-5 my-4 h-[22rem] min-h-0", showKeypad && "grid gap-4 sm:grid-cols-[minmax(0,1fr)_15rem]")}>
        <div className={cn("relative h-full min-h-0", showKeypad && "max-sm:hidden")}>
          {s.phase === "error" && s.problem ? (
            <ProblemCallout problem={s.problem} />
          ) : s.turns.length === 0 ? (
            <EmptyTranscript phase={s.phase} />
          ) : (
            <Transcript turns={s.turns} reduce={reduce} />
          )}
        </div>
        {showKeypad && <Keypad onPress={sendDigit} className="justify-center sm:border-l sm:border-line sm:pl-4" />}
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
                label={keypadOpen ? "Hide keypad" : "Show keypad"}
                aria-pressed={keypadOpen}
                onClick={() => setKeypadOpen((o) => !o)}
                disabled={s.phase === "ending"}
                className={cn("border border-line-strong", keypadOpen && "border-transparent bg-accent-soft text-accent-text hover:bg-accent-soft")}
              >
                <Grid3x3 aria-hidden />
              </IconButton>
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

function footerHint(s: WebCallState, elapsed: number, cost: bigint): string {
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
  // Speaking: the wave follows the level. Quiet but connected: an even line with a soft sweep.
  const scale = active && !reduce ? 0.3 + 0.7 * Math.min(1, level * 1.4) : 1;
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-3 rounded-control bg-surface-2 py-2 pl-3 pr-3">
      <div className="flex min-w-0 flex-col leading-tight">
        <span className="text-[12.5px] font-medium text-fg">{label}</span>
        <span className={cn("text-[11.5px]", muted ? "text-warning-text" : active ? "text-accent-text" : "text-fg-3")}>{status}</span>
      </div>
      <div
        aria-hidden
        className={cn("h-7 origin-center", !reduce && "transition-transform duration-150 ease-out")}
        style={{ transform: `scaleY(${scale})` }}
      >
        <Waveform bars={36} seed={seed} progress={active ? 1 : 0} live={active} height={28} flat={muted || idle} quiet={!active && !muted && !idle} />
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
      {turns.map((t, i) => {
        const agent = t.who === "agent";
        // The speaker's name only when the speaker changes, so a run of turns reads as one voice.
        const first = turns[i - 1]?.who !== t.who;
        return (
          <motion.li
            key={t.id}
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.24, ease: EASE_OUT }}
            className={cn("flex flex-col gap-1", agent ? "items-start" : "items-end", !first && "-mt-1.5")}
          >
            {first && (
              <span className={cn("flex items-center gap-1.5 text-[11.5px] font-medium text-fg-3", !agent && "flex-row-reverse")}>
                <span
                  aria-hidden
                  className={cn(
                    "grid size-5 place-items-center rounded-full [&_svg]:size-3",
                    agent ? "grad-action text-white" : "bg-surface-2 text-fg-2",
                  )}
                >
                  {agent ? <Bot /> : <User />}
                </span>
                {agent ? "Agent" : "You"}
              </span>
            )}
            <p
              className={cn(
                "max-w-[min(46ch,82%)] rounded-panel px-3.5 py-2 text-[13.5px] leading-relaxed transition-colors duration-200",
                agent ? "rounded-tl-[6px] bg-surface-2" : "rounded-tr-[6px] bg-accent-soft",
                t.final ? "text-fg" : "text-fg-2",
              )}
            >
              {t.text}
            </p>
            {t.latency && <LatencyChip latency={t.latency} />}
          </motion.li>
        );
      })}
    </ol>
  );
});
