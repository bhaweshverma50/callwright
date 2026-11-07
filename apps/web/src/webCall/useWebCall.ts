/**
 * The browser call state machine behind `WebCallPanel` and the home page playground: microphone
 * check, session, room, then live until either side hangs up. A driver (webCall.ts) does the I/O,
 * so the same machine runs against the API, the public demo endpoint or a scripted mock call.
 */
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { Latency } from "../components/signal";
import {
  CONNECTION_FAILED,
  MIC_DENIED,
  MIC_UNAVAILABLE,
  problemFromError,
  type AgentActivity,
  type CallConnection,
  type CallLevels,
  type CallListener,
  type CallProblem,
  type CallTurn,
  type EndReason,
  type WebCallDriver,
  type WebCallRequest,
} from "./webCall";
import { queryClient } from "../api/queryClient";
import { callKeys } from "../api/calls";
import { idempotencyKey } from "../lib/idempotency";

export type CallPhase = "idle" | "checking" | "requesting" | "connecting" | "live" | "ending" | "ended" | "error";

export interface CallSummary {
  callId: string | null;
  durationMs: number;
  reason: EndReason;
}

export interface WebCallState {
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

const INITIAL: WebCallState = {
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

function reducer(s: WebCallState, a: Action): WebCallState {
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

export function useWebCall(
  driver: WebCallDriver,
  request: WebCallRequest,
  onEnded?: (summary: CallSummary) => void,
  /** Rewords a refused session for this surface; falls back to `problemFromError`. */
  problemFor?: (e: unknown) => CallProblem | undefined,
) {
  const [s, dispatch] = useReducer(reducer, INITIAL);
  const run = useRef(0);
  const conn = useRef<CallConnection | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;
  const requestRef = useRef(request);
  requestRef.current = request;
  const problemForRef = useRef(problemFor);
  problemForRef.current = problemFor;

  useEffect(() => {
    if (s.phase !== "live" && s.phase !== "ending") return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [s.phase]);

  // The shell's live-calls badge and the dashboard card pick the call up (and drop it) at once
  // instead of on their next idle poll.
  useEffect(() => {
    if (s.phase === "live" || s.phase === "ended") void queryClient.invalidateQueries({ queryKey: callKeys.live });
  }, [s.phase]);

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
      session = await driver.createSession(requestRef.current, idempotencyKey());
    } catch (e) {
      if (!stale()) dispatch({ type: "fail", problem: problemForRef.current?.(e) ?? problemFromError(e) });
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
  }, [driver]);

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

  const sendDigit = useCallback((digit: string) => {
    void conn.current?.sendDigit?.(digit).catch(() => {});
  }, []);

  const elapsed = s.startedAt ? (s.endedAt ?? now) - s.startedAt : 0;
  return { state: s, start, cancel, end, toggleMute, sendDigit, elapsed };
}
