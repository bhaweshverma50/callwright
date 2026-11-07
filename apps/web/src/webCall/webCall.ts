/**
 * Browser test call plumbing for `WebCallPanel` (spec 003, US1, FR-047, research R17).
 *
 * The panel talks to a `WebCallDriver`, which has three steps that always run in this order:
 *
 * 1. `checkMicrophone()`: confirms microphone access BEFORE any session is requested, so a
 *    blocked microphone never creates or charges a call.
 * 2. `createSession()`: `POST /v1/sessions/web-call` (admission, room, worker dispatch).
 * 3. `connect()`: joins the room and reports agent state, transcript turns, per-turn latency and
 *    audio levels to a `CallListener` until the call ends.
 *
 * `createLiveDriver()` (webCallLive.ts) does this against the API and LiveKit. `createMockDriver()`
 * below plays a scripted call on timers so the panel works in the gallery, in MSW mock mode and in
 * tests without a media server.
 */
import type { Latency } from "../components/signal";
import { ApiError, isApiError } from "../api/errors";
import { isInsufficientCredit } from "../api/paid";
import { BILLING_PATH } from "../lib/paths";
import type { Problem } from "../api/types";

export type MicCheck = "granted" | "denied" | "unavailable";
/** What the agent is doing, from the `lk.agent.state` participant attribute. */
export type AgentActivity = "joining" | "listening" | "thinking" | "speaking";
export type EndReason = "user_hangup" | "agent_hangup" | "connection_lost";

export interface CallTurn {
  /** Transcript segment id; interim updates for the same segment replace its text. */
  id: string;
  who: "caller" | "agent";
  text: string;
  final: boolean;
  latency?: Latency;
}

export interface CallLevels {
  /** 0 to 1. */
  caller: number;
  agent: number;
}

export interface WebCallRequest {
  agent_id: string;
  version?: string;
  dynamic_variables?: Record<string, string>;
}

/** The `WebCallSession` body from `POST /v1/sessions/web-call` (contracts/sessions.yaml). */
export interface WebCallSessionInfo {
  call_id: string;
  room_name: string;
  server_url: string;
  participant_token: string;
  expires_at: string;
  missing_variables?: string[];
}

export interface CallListener {
  activity(a: AgentActivity): void;
  /** Adds the turn, or replaces the text of the turn with the same id. */
  turn(t: CallTurn): void;
  /** Latency for an agent turn; `turnId` null means the latest agent turn. */
  latency(turnId: string | null, l: Latency): void;
  levels(l: CallLevels): void;
  ended(reason: EndReason): void;
}

export interface CallConnection {
  setMuted(muted: boolean): Promise<void>;
  hangUp(): Promise<void>;
  /** Sends a keypad press (0-9, *, #) as DTMF. Absent when the call cannot carry key presses. */
  sendDigit?(digit: string): Promise<void>;
}

/** DTMF event codes (RFC 4733) for the keypad keys. */
export const DTMF_CODES: Record<string, number> = {
  "0": 0,
  "1": 1,
  "2": 2,
  "3": 3,
  "4": 4,
  "5": 5,
  "6": 6,
  "7": 7,
  "8": 8,
  "9": 9,
  "*": 10,
  "#": 11,
};

export interface WebCallDriver {
  /** True for simulated calls; the panel labels them so nobody mistakes one for a real call. */
  readonly simulated: boolean;
  checkMicrophone(): Promise<MicCheck>;
  createSession(req: WebCallRequest, idempotencyKey: string): Promise<WebCallSessionInfo>;
  connect(session: WebCallSessionInfo, listener: CallListener): Promise<CallConnection>;
}

/** Data topic the worker publishes per-turn latency on: JSON `{segment_id?, stt_ms, llm_ms, tts_ms}`. */
export const LATENCY_TOPIC = "cw.turn_latency";

/** Something the operator should read and can usually fix. */
export interface CallProblem {
  kind: "mic_denied" | "mic_unavailable" | "refused" | "network" | "connection";
  title: string;
  detail: string;
  /** A link that fixes the cause (Add funds). */
  action?: { label: string; href: string };
}

const NOT_CHARGED = "No call was created and nothing was charged.";

export const MIC_DENIED: CallProblem = {
  kind: "mic_denied",
  title: "Microphone access is blocked",
  detail: `Open the site settings from the icon at the left of the address bar, allow Microphone, then try again. ${NOT_CHARGED}`,
};

export const MIC_UNAVAILABLE: CallProblem = {
  kind: "mic_unavailable",
  title: "No microphone found",
  detail: `Connect a microphone, or check that this page is served over HTTPS, then try again. ${NOT_CHARGED}`,
};

export const CONNECTION_FAILED: CallProblem = {
  kind: "connection",
  title: "Could not join the call",
  detail: "The call server did not answer. Try again; calls are charged only once they connect.",
};

/** Turns a failed session request into words the operator can act on. */
export function problemFromError(e: unknown): CallProblem {
  if (!isApiError(e)) return { kind: "network", title: "Could not start the call", detail: "Something went wrong. Try again." };
  const p = e.problem;
  if (e.status === 0) return { kind: "network", title: "Could not reach Callwright", detail: "Check your connection and try again." };
  if (isInsufficientCredit(e))
    return {
      kind: "refused",
      title: "Not enough credit",
      detail: "Add funds to keep making test calls. The refused attempt was not charged.",
      action: { label: "Add funds", href: BILLING_PATH },
    };
  if (e.status === 403 || p.code === "email_unverified")
    return { kind: "refused", title: "Verify your email first", detail: "Open the link we emailed you, then start the test call again." };
  if (e.status === 429 || p.code === "concurrency_limit")
    return {
      kind: "refused",
      title: "Too many calls at once",
      detail: p.detail ?? "Your workspace is at its concurrent call limit. End another call or wait a moment, then try again.",
    };
  // The wake gate (api/wakeGate.ts) already waited for the call servers; this is what is left
  // when they did not start in time.
  if (e.status === 503 && p.code === "waking_up")
    return {
      kind: "network",
      title: "The call servers are still starting",
      detail: `They sleep when nobody is calling and usually start within a minute. Wait a moment, then start the call again. ${NOT_CHARGED}`,
    };
  if (e.status === 503 || p.code === "media_unavailable")
    return {
      kind: "network",
      title: "The call server is unavailable",
      detail: "The call could not start and was not charged. Try again in a moment.",
    };
  if (e.status === 409 && p.code === "agent_not_published")
    return { kind: "refused", title: "This agent is not published yet", detail: "Publish a version first, or test the draft instead." };
  return { kind: "refused", title: p.title || "The call was refused", detail: p.detail ?? "Try again in a moment." };
}

// ---------------------------------------------------------------------------------------------
// Mock driver: a scripted call on timers.

export interface MockStep {
  who: "caller" | "agent";
  text: string;
  /** Agent turns only: the latency shown on its chip. Leave out for the greeting. */
  latency?: Latency;
}

/** A dental front desk call, agent first. Mirrors the sample call on the home page. */
export const MOCK_SCRIPT: MockStep[] = [
  { who: "agent", text: "Hi, thanks for calling Halcyon Dental. How can I help today?" },
  { who: "caller", text: "Hi, I need to move my cleaning on Tuesday. Something came up at work." },
  {
    who: "agent",
    text: "No problem. I can see your 9:30 with Dr. Okafor. Thursday has 10:40 or 2:15. Which works?",
    latency: { stt: 160, llm: 310, tts: 140 },
  },
  { who: "caller", text: "2:15 is good." },
  {
    who: "agent",
    text: "Done. You're booked for Thursday at 2:15. I'll text you a reminder the day before.",
    latency: { stt: 150, llm: 280, tts: 130 },
  },
];

export interface MockOptions {
  microphone?: MicCheck;
  /** Refuse the session request with this HTTP status (402, 403, 429, 422). */
  refuseWith?: number;
  /** Fail while joining the room. */
  failConnect?: boolean;
  /** Milliseconds to answer the session request and to join the room. */
  requestDelayMs?: number;
  connectDelayMs?: number;
  /** Milliseconds per word while a side speaks. */
  wordMs?: number;
  /** Milliseconds of silence after each agent turn. */
  gapMs?: number;
  script?: MockStep[];
}

const REFUSALS: Record<number, Problem> = {
  402: { type: "https://callwright.dev/problems/insufficient-credit", code: "insufficient_credit", title: "Insufficient credit", status: 402 },
  403: { type: "https://callwright.dev/problems/email-unverified", code: "email_unverified", title: "Email not verified", status: 403 },
  429: {
    type: "https://callwright.dev/problems/concurrency-limit",
    code: "concurrency_limit",
    title: "Concurrency limit reached",
    status: 429,
    detail: "Your workspace allows 5 calls at once and 5 are running. End one or wait, then try again.",
  },
  422: {
    type: "https://callwright.dev/problems/pricing-unavailable",
    code: "pricing_unavailable",
    title: "This configuration has no price yet",
    status: 422,
    detail: "Pick a listed voice or model in the agent's settings, then try again.",
  },
};

/** Promise-based sleep that rejects when the signal aborts, so a hung-up script stops at once. */
function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException("aborted", "AbortError"));
    const t = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function createMockDriver(opts: MockOptions = {}): WebCallDriver {
  const {
    microphone = "granted",
    refuseWith,
    failConnect = false,
    requestDelayMs = 500,
    connectDelayMs = 900,
    wordMs = 230,
    gapMs = 700,
    script = MOCK_SCRIPT,
  } = opts;
  return {
    simulated: true,
    checkMicrophone: async () => microphone,
    async createSession(req) {
      await new Promise((r) => setTimeout(r, requestDelayMs));
      if (refuseWith) throw new ApiError(refuseWith, REFUSALS[refuseWith] ?? { type: "about:blank", title: "Refused", status: refuseWith });
      return {
        call_id: "call_01JMOCKCALL0000000000000000",
        room_name: `call-mock-${req.agent_id}`,
        server_url: "wss://mock.invalid",
        participant_token: "mock",
        expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
      };
    },
    async connect(_session, listener) {
      await new Promise((r) => setTimeout(r, connectDelayMs));
      if (failConnect) throw new Error("mock connection failure");
      const ctrl = new AbortController();
      const signal = ctrl.signal;
      let muted = false;
      let speaking: "caller" | "agent" | null = null;
      let phase = 0;

      // Levels: a soft speech-like envelope for the side that is talking, a noise floor otherwise.
      const emitLevels = () => {
        phase += 1;
        const voice = 0.45 + 0.35 * Math.abs(Math.sin(phase * 0.9)) + 0.2 * Math.abs(Math.sin(phase * 2.3));
        listener.levels({
          caller: speaking === "caller" && !muted ? Math.min(1, voice) : 0.03,
          agent: speaking === "agent" ? Math.min(1, voice) : 0.03,
        });
      };
      const levelTimer = setInterval(emitLevels, 100);

      async function speak(id: string, step: MockStep) {
        const words = step.text.split(" ");
        speaking = step.who;
        emitLevels();
        if (step.who === "agent") listener.activity("speaking");
        for (let i = 1; i <= words.length; i++) {
          listener.turn({ id, who: step.who, text: words.slice(0, i).join(" "), final: false });
          if (i === 1 && step.latency) listener.latency(id, step.latency);
          await sleep(wordMs, signal);
        }
        listener.turn({ id, who: step.who, text: step.text, final: true });
        speaking = null;
        emitLevels();
      }

      async function run() {
        listener.activity("listening");
        await sleep(400, signal);
        for (const [i, step] of script.entries()) {
          const id = `mock-${i}`;
          if (step.who === "caller") {
            while (muted) await sleep(200, signal);
            await speak(id, step);
            listener.activity("thinking");
            const l = script[i + 1]?.latency;
            await sleep(l ? l.stt + l.llm + l.tts : 500, signal);
          } else {
            await speak(id, step);
            listener.activity("listening");
            await sleep(gapMs, signal);
          }
        }
      }
      run().catch(() => {
        /* aborted by hang up */
      });

      return {
        async setMuted(m) {
          muted = m;
          emitLevels();
        },
        async hangUp() {
          ctrl.abort();
          clearInterval(levelTimer);
          listener.ended("user_hangup");
        },
        async sendDigit() {
          /* the scripted call ignores key presses */
        },
      };
    },
  };
}
