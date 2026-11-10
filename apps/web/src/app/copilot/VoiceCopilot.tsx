import { AudioLines, Keyboard, Loader2, Mic, MicOff, Send, WifiOff, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { fetchStreamCredential, interpretCommand, transcribeCommand } from "../../api/assistants";
import { isApiError } from "../../api/errors";
import { useLazyToken } from "../../api/lazyToken";
import type { components } from "../../api/schema";
import { cn, focusRing, Kbd, Tooltip } from "../../components";
import { openAsk } from "../assistant/bus";
import { highlight, highlightableElements, registeredActions, runAction } from "./actionRegistry";
import { openDeepgramStream, type LiveTranscriber } from "./stt/deepgram";
import { viewerTimeZone } from "../../lib/format";
import { CALLS_PATH, callsPath } from "../../lib/paths";
import { bodyLimits } from "../../lib/contract.gen";

const TRANSCRIPT_MAX = bodyLimits["POST /voice-commands/interpret"].transcript.maxLength;
type Interpret = components["schemas"]["InterpretResult"];
type Phase = "idle" | "starting" | "listening" | "transcribing" | "thinking" | "done";
type Notice = { tone: "info" | "error"; text: string; hint?: string; icon?: "offline" | "mic" } | null;
type Mode = "hold" | "toggle";

const RETRY_HINT_AFTER = 2;
const MAX_LISTEN_MS = 30_000;

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== "function") return false;
  return (
    el.isContentEditable ||
    /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) ||
    Boolean(el.closest('[role=textbox],[contenteditable=""],[contenteditable="true"],[contenteditable="plaintext-only"]'))
  );
}

/** Widgets whose own Space behaviour (toggle, pick, open) must win over push-to-talk. */
const SPACE_WIDGETS =
  "[role=menu],[role=menuitem],[role=menuitemcheckbox],[role=menuitemradio],[role=option],[role=listbox],[role=combobox],[role=slider],[role=spinbutton],[role=checkbox],[role=radio],[role=switch],[role=tab],[role=tree],[role=grid],summary";

/**
 * Whether a Space press may start push-to-talk. Anywhere except text entry and widgets that use
 * Space. A button or link keeps its native Space activation only when it was reached with the
 * keyboard (`keyboardFocus`, Tab since the last pointer press); after a mouse click the focus is
 * left on whatever was clicked, and that used to swallow every later Space press. (`:focus-visible`
 * cannot tell: Chrome turns it on for the focused element as soon as any key is pressed.)
 */
export function spaceStartsTalk(target: EventTarget | null, keyboardFocus = false): boolean {
  if (isTyping(target)) return false;
  const el = target instanceof HTMLElement ? target : null;
  if (!el || el === document.body || el === document.documentElement) return true;
  if (el.closest(SPACE_WIDGETS)) return false;
  if (el.closest("button, a[href], [role=button]")) return !keyboardFocus;
  return true;
}

type Capture = { stream: MediaStream; recorder: MediaRecorder; chunks: Blob[]; live: LiveTranscriber | null };

function release(m: Capture) {
  m.stream.getTracks().forEach((t) => t.stop());
  m.live?.close();
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The Call History address for a validated navigate result (date ranges become calendar dates). */
export function callsUrl(params: Record<string, unknown> | null | undefined, now = new Date()): string {
  const list = (key: string) => {
    const v = params?.[key];
    return Array.isArray(v) ? v.map(String) : undefined;
  };
  const day = (offset: number) => iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset));
  const dates: Record<string, [string, string]> = {
    today: [day(0), day(0)],
    yesterday: [day(-1), day(-1)],
    this_week: [day(-((now.getDay() + 6) % 7)), day(0)],
    last_7_days: [day(-6), day(0)],
  };
  const range = typeof params?.date_range === "string" ? dates[params.date_range] : undefined;
  return callsPath({
    status: list("status"),
    channel: list("channel"),
    sentiment: list("sentiment"),
    agent_id: typeof params?.agent_id === "string" ? params.agent_id : undefined,
    start_date: range?.[0],
    end_date: range?.[1],
  });
}

/**
 * Push-to-talk voice copilot (US6): hold Space anywhere outside text fields, or press the mic
 * (press again to send). Speech streams to the transcription vendor with a 60 s token minted on
 * first use (never on page load); if streaming fails the clip is recorded and transcribed after
 * release, and when the server has no transcription vendor at all the copilot says so and offers
 * typing. The server interprets and validates; this component only performs what came back.
 *
 * `placement` "dock" opens its status card above the floating dock; "bar" opens it below the top
 * bar (full-height editors). `spaceToTalk` is off where Space already means something (the flow
 * canvas pans with it).
 */
export function VoiceCopilot({ placement = "dock", spaceToTalk = true }: { placement?: "dock" | "bar"; spaceToTalk?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [phase, setPhaseState] = useState<Phase>("idle");
  const [mode, setMode] = useState<Mode>("hold");
  const [notice, setNotice] = useState<Notice>(null);
  const [partial, setPartial] = useState("");
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [failures, setFailures] = useState(0);
  const phaseRef = useRef<Phase>("idle");
  const held = useRef(false);
  const notConfigured = useRef(false);
  const limitTimer = useRef<number | null>(null);
  const history = useRef<{ role: "user" | "copilot"; content: string }[]>([]);
  const media = useRef<Capture | null>(null);
  const supported = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";

  const setPhase = useCallback((p: Phase) => {
    phaseRef.current = p;
    setPhaseState(p);
  }, []);

  const streamCredential = useLazyToken(fetchStreamCredential);

  const fail = useCallback(
    (text: string, hint?: string) => {
      setNotice({ tone: "error", text, hint });
      setPhase("done");
      setFailures((n) => {
        const next = n + 1;
        if (next >= RETRY_HINT_AFTER) setTyping(true);
        return next;
      });
    },
    [setPhase],
  );

  const offerTyping = useCallback(
    (text: string, hint: string, icon?: "offline" | "mic") => {
      setNotice({ tone: "error", text, hint, icon });
      setTyping(true);
      setPhase("done");
    },
    [setPhase],
  );

  const perform = useCallback(
    (r: Interpret) => {
      history.current = [...history.current, { role: "copilot" as const, content: r.speak ?? r.action }].slice(-12);
      setFailures(0);
      if (r.action === "navigate" && r.target) {
        navigate(r.target === CALLS_PATH ? callsUrl(r.params) : r.target);
        setNotice({ tone: "info", text: r.speak ?? "Done." });
      } else if (r.action === "route_to_copilot") {
        if (r.target === "analytics_chat") openAsk(r.query ?? undefined);
        setNotice({
          tone: "info",
          text: r.target === "analytics_chat" ? "Opening the analytics assistant." : "That assistant opens from its builder page.",
        });
      } else if (r.action === "ui_action" && r.target) {
        const ran = runAction(r.target, r.params ?? null);
        setNotice(ran ? { tone: "info", text: r.speak ?? "Done." } : { tone: "error", text: "This page can't do that any more." });
      } else if (r.action === "answer") {
        setNotice({ tone: "info", text: r.speak ?? "" });
      } else {
        if (r.highlight_element) highlight(r.highlight_element);
        setNotice({ tone: "error", text: r.speak ?? "I can't do that here.", hint: r.fallback_suggestion ?? undefined });
      }
      setPhase("done");
    },
    [navigate, setPhase],
  );

  const interpret = useCallback(
    async (transcript: string) => {
      const text = transcript.trim();
      if (!text) {
        fail("Didn't catch that.", "Hold Space (or press the mic) and speak a little longer.");
        return;
      }
      setPhase("thinking");
      setPartial(text);
      history.current = [...history.current, { role: "user" as const, content: text }].slice(-12);
      try {
        const result = await interpretCommand({
          transcript: text.slice(0, TRANSCRIPT_MAX),
          visual_state: {
            current_route: location.pathname,
            page_title: document.title,
            current_datetime: new Date().toISOString(),
            timezone: viewerTimeZone(),
            available_actions: registeredActions(),
            highlightable_elements: highlightableElements(),
          },
          conversation_history: history.current.slice(0, -1),
        });
        perform(result);
      } catch {
        fail(navigator.onLine ? "The copilot could not answer. Try again." : "You're offline.");
      }
    },
    [fail, location.pathname, perform, setPhase],
  );

  const clearLimit = useCallback(() => {
    if (limitTimer.current !== null) window.clearTimeout(limitTimer.current);
    limitTimer.current = null;
  }, []);

  const stop = useCallback(async () => {
    const m = media.current;
    if (!m) return;
    media.current = null;
    clearLimit();
    setPhase("transcribing");
    const stopped = new Promise<void>((r) => (m.recorder.onstop = () => r()));
    m.recorder.stop();
    await stopped;
    m.stream.getTracks().forEach((t) => t.stop());
    let text = "";
    try {
      if (m.live) text = await m.live.finish();
      else if (m.chunks.length === 0) text = "";
      else {
        text = (await transcribeCommand(new Blob(m.chunks, { type: "audio/webm" }))).transcript;
      }
    } catch (e) {
      if (isApiError(e) && e.code === "stt_not_configured") {
        notConfigured.current = true;
        offerTyping("Voice input isn't available here.", "Speech transcription isn't set up on this server. Type the command instead.");
      } else fail("Transcription failed.", "Try again, or type the command.");
      return;
    } finally {
      m.live?.close();
    }
    await interpret(text);
  }, [clearLimit, fail, interpret, offerTyping, setPhase]);

  const start = useCallback(
    async (how: Mode) => {
      if (phaseRef.current === "listening" || phaseRef.current === "starting") return;
      setNotice(null);
      setPartial("");
      setMode(how);
      if (!navigator.onLine) {
        offerTyping("You're offline.", "Voice commands need a connection.", "offline");
        return;
      }
      if (notConfigured.current) {
        offerTyping("Voice input isn't available here.", "Speech transcription isn't set up on this server. Type the command instead.");
        return;
      }
      setPhase("starting");
      let prompted = false;
      let stream: MediaStream | null = null;
      try {
        const perm = await navigator.permissions?.query({ name: "microphone" as PermissionName }).catch(() => null);
        if (perm?.state === "denied") throw new DOMException("denied", "NotAllowedError");
        prompted = perm?.state === "prompt";
        // The microphone and the streaming credential are requested together to keep start-up short.
        const [gotStream, credential] = await Promise.all([
          navigator.mediaDevices.getUserMedia({ audio: true }),
          streamCredential().then(
            (value) => ({ ok: true as const, value }),
            (error: unknown) => ({ ok: false as const, error }),
          ),
        ]);
        stream = gotStream;
        if (!credential.ok && isApiError(credential.error) && credential.error.code === "stt_not_configured") {
          notConfigured.current = true;
          stream.getTracks().forEach((t) => t.stop());
          offerTyping("Voice input isn't available here.", "Speech transcription isn't set up on this server. Type the command instead.");
          return;
        }
        let live: LiveTranscriber | null = null;
        if (credential.ok) {
          try {
            live = await openDeepgramStream(credential.value, setPartial);
          } catch {
            live = null; // record now, transcribe after release
          }
        }
        const mime = MediaRecorder.isTypeSupported?.("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : undefined;
        const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
        const chunks: Blob[] = [];
        recorder.ondataavailable = (e) => {
          if (e.data.size) {
            chunks.push(e.data);
            live?.send(e.data);
          }
        };
        const m = { stream, recorder, chunks, live };
        if (how === "hold" && !held.current) {
          // Space came up while the microphone was starting (often the permission prompt).
          release(m);
          setNotice({
            tone: "info",
            icon: "mic",
            text: prompted ? "Microphone ready." : "Keep holding Space while you speak.",
            hint: prompted ? "Hold Space while you speak, release to send." : "Release it when you're done to send the command.",
          });
          setPhase("done");
          return;
        }
        recorder.start(250);
        media.current = m;
        setPhase("listening");
        limitTimer.current = window.setTimeout(() => void stop(), MAX_LISTEN_MS);
      } catch (e) {
        stream?.getTracks().forEach((t) => t.stop());
        const blocked = e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError");
        const missing = e instanceof DOMException && e.name === "NotFoundError";
        offerTyping(
          blocked ? "Microphone blocked." : missing ? "No microphone found." : "The microphone did not start.",
          blocked ? "Allow the microphone from the icon in the address bar, or type the command." : "Type the command instead.",
          "mic",
        );
      }
    },
    [streamCredential, offerTyping, setPhase, stop],
  );

  const cancel = useCallback(() => {
    const m = media.current;
    if (!m) return;
    media.current = null;
    clearLimit();
    m.recorder.onstop = null;
    if (m.recorder.state !== "inactive") m.recorder.stop();
    release(m);
    setNotice({ tone: "info", text: "Cancelled." });
    setPhase("done");
  }, [clearLimit, setPhase]);

  useEffect(() => {
    if (!supported || !spaceToTalk) return;
    let keyboardFocus = false;
    const pointer = () => {
      keyboardFocus = false;
    };
    const down = (e: KeyboardEvent) => {
      if (e.key === "Tab") keyboardFocus = true;
      if (e.code !== "Space" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.repeat) {
        if (held.current) e.preventDefault(); // no page scroll while holding
        return;
      }
      if (!spaceStartsTalk(e.target, keyboardFocus)) return;
      e.preventDefault(); // no scroll, and no click on a mouse-focused button
      held.current = true;
      void start("hold");
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || !held.current) return;
      e.preventDefault();
      held.current = false;
      if (media.current && phaseRef.current === "listening") void stop();
    };
    const blur = () => {
      if (held.current && media.current) void stop();
      held.current = false;
    };
    window.addEventListener("pointerdown", pointer, true);
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("pointerdown", pointer, true);
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("blur", blur);
    };
  }, [spaceToTalk, start, stop, supported]);

  useEffect(() => {
    if (phase !== "listening") return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && cancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancel, phase]);

  useEffect(
    () => () => {
      clearLimit();
      if (media.current) release(media.current);
    },
    [clearLimit],
  );

  useEffect(() => {
    if (phase !== "done" || typing) return;
    const t = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(t);
  }, [phase, notice, typing]);

  const submitTyped = (e: FormEvent) => {
    e.preventDefault();
    const text = typed.trim();
    if (!text) return;
    setTyped("");
    void interpret(text);
  };

  const listening = phase === "listening";
  const busy = phase === "starting" || phase === "transcribing" || phase === "thinking";
  const sendHint = mode === "hold" ? "Release Space to send" : "Press the mic again to send";
  const status =
    phase === "starting"
      ? "Starting the microphone"
      : listening
        ? partial || "Listening"
        : phase === "transcribing"
          ? "Transcribing"
          : phase === "thinking"
            ? `"${partial}"`
            : null;
  const showTypingHint = failures >= RETRY_HINT_AFTER;
  const bar = placement === "bar";
  const size = bar ? "size-8" : "size-9";

  return (
    <div className="relative flex items-center gap-1">
      <AnimatePresence>
        {(status || notice || typing) && (
          <motion.div
            initial={{ opacity: 0, y: bar ? -8 : 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: bar ? -8 : 8, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            role="status"
            aria-live="polite"
            className={cn(
              "absolute right-0 z-50 w-[min(320px,calc(100vw-32px))] rounded-panel border border-line bg-surface p-3 shadow-pop",
              bar ? "top-[calc(100%+10px)]" : "bottom-[calc(100%+12px)]",
            )}
          >
            {status && (
              <div className="flex flex-col gap-1">
                <p className="flex items-center gap-2 text-[13px] text-fg">
                  {listening ? (
                    <span className="flex h-3.5 items-end gap-[2px]" aria-hidden>
                      {[0, 1, 2, 3].map((i) => (
                        <motion.span
                          key={i}
                          className="w-[3px] rounded-full bg-on-air"
                          animate={{ height: ["30%", "100%", "45%"] }}
                          transition={{ duration: 0.7, repeat: Infinity, delay: i * 0.12 }}
                        />
                      ))}
                    </span>
                  ) : phase === "transcribing" ? (
                    <AudioLines className="size-3.5 animate-pulse text-accent-text" aria-hidden />
                  ) : (
                    <Loader2 className="size-3.5 animate-spin text-accent-text" aria-hidden />
                  )}
                  <span className="min-w-0 truncate">{status}</span>
                </p>
                {listening && (
                  <p className="pl-[22px] text-[12px] text-fg-3">
                    {sendHint}. <Kbd>Esc</Kbd> cancels.
                  </p>
                )}
              </div>
            )}
            {!status && notice && (
              <div className="flex items-start gap-2">
                {notice.icon === "offline" ? (
                  <WifiOff className="mt-0.5 size-4 shrink-0 text-danger-text" aria-hidden />
                ) : notice.tone === "error" ? (
                  <MicOff className="mt-0.5 size-4 shrink-0 text-danger-text" aria-hidden />
                ) : (
                  <Mic className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] text-fg">{notice.text}</p>
                  {notice.hint && <p className="mt-0.5 text-[12px] text-fg-3">{notice.hint}</p>}
                  {showTypingHint && <p className="mt-1 text-[12px] font-medium text-accent-text">Try typing instead.</p>}
                </div>
                <button
                  type="button"
                  aria-label="Dismiss"
                  onClick={() => {
                    setNotice(null);
                    setTyping(false);
                  }}
                  className={cn("grid size-6 cursor-pointer place-items-center rounded-control text-fg-3 hover:bg-surface-3", focusRing)}
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </div>
            )}
            {typing && !status && (
              <form onSubmit={submitTyped} className={cn("flex items-center gap-1.5", notice && "mt-2.5")}>
                <label htmlFor="copilot-typed" className="sr-only">
                  Type a command
                </label>
                <input
                  id="copilot-typed"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="Show failed calls from yesterday"
                  maxLength={TRANSCRIPT_MAX}
                  autoFocus
                  className={cn(
                    "h-8 min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-2.5 text-[13px] text-fg placeholder:text-fg-3",
                    focusRing,
                  )}
                />
                <button
                  type="submit"
                  aria-label="Send command"
                  className={cn("bg-accent grid size-8 cursor-pointer place-items-center rounded-control text-white", focusRing)}
                >
                  <Send className="size-3.5" aria-hidden />
                </button>
              </form>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      <Tooltip content="Type a command" side={bar ? "bottom" : "top"}>
        <button
          type="button"
          aria-label="Type a command"
          aria-pressed={typing}
          onClick={() => setTyping((t) => !t)}
          className={cn(
            size,
            "grid cursor-pointer place-items-center rounded-full text-fg-2 transition-[color,background-color,transform] duration-150 hover:bg-surface-2 hover:text-fg active:scale-95",
            typing && "bg-surface-2 text-fg",
            focusRing,
          )}
        >
          <Keyboard className="size-4" aria-hidden />
        </button>
      </Tooltip>
      {supported && (
        <Tooltip
          side={bar ? "bottom" : "top"}
          content={
            listening ? (
              "Send the command"
            ) : spaceToTalk ? (
              <span className="flex items-center gap-1.5">
                Hold <Kbd>Space</Kbd> or press to talk
              </span>
            ) : (
              "Press to talk"
            )
          }
        >
          <button
            type="button"
            aria-label={listening ? "Stop listening and send" : "Talk to the copilot"}
            aria-pressed={listening}
            onClick={() => (listening ? void stop() : busy ? undefined : void start("toggle"))}
            className={cn(
              size,
              "relative grid cursor-pointer place-items-center rounded-full transition-[transform,background-color,color] duration-150 active:scale-95",
              // Secondary until it is live: "Ask about your data" is the dock's one gradient action.
              listening ? "bg-on-air text-white" : "bg-accent-soft text-accent-text hover:bg-accent hover:text-white",
              focusRing,
            )}
          >
            {listening && <span aria-hidden className="on-air-pulse absolute inset-0 rounded-full" />}
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Mic className="relative size-4" aria-hidden />}
          </button>
        </Tooltip>
      )}
    </div>
  );
}
