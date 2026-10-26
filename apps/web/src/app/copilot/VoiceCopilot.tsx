import { Keyboard, Loader2, Mic, MicOff, Send, WifiOff, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { api, unwrap } from "../../api/client";
import { useLazyToken } from "../../api/lazyToken";
import type { components } from "../../api/schema";
import { cn, focusRing, Kbd, Tooltip } from "../../components";
import { viewerTimeZone } from "../../routes/calls/filters";
import { openAsk } from "../assistant/bus";
import { highlight, highlightableElements, registeredActions, runAction } from "./actionRegistry";
import { openDeepgramStream, type LiveTranscriber, type StreamCredential } from "./stt/deepgram";

type Interpret = components["schemas"]["InterpretResult"];
type Phase = "idle" | "starting" | "listening" | "transcribing" | "thinking" | "done";
type Notice = { tone: "info" | "error"; text: string; hint?: string } | null;

const RETRY_HINT_AFTER = 2;

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.getAttribute("role") === "textbox");
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The Call History address for a validated navigate result (date ranges become calendar dates). */
export function callsUrl(params: Record<string, unknown> | null | undefined, now = new Date()): string {
  const q = new URLSearchParams();
  for (const key of ["status", "channel", "sentiment"]) {
    const v = params?.[key];
    if (Array.isArray(v) && v.length) q.set(key, v.join(","));
  }
  if (typeof params?.agent_id === "string") q.set("agent_id", params.agent_id);
  const day = (offset: number) => iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset));
  const range = params?.date_range;
  const dates: Record<string, [string, string]> = {
    today: [day(0), day(0)],
    yesterday: [day(-1), day(-1)],
    this_week: [day(-((now.getDay() + 6) % 7)), day(0)],
    last_7_days: [day(-6), day(0)],
  };
  if (typeof range === "string" && dates[range]) {
    q.set("start_date", dates[range]![0]);
    q.set("end_date", dates[range]![1]);
  }
  const s = q.toString();
  return s ? `/calls?${s}` : "/calls";
}

/**
 * Push-to-talk voice copilot (US6): hold Space outside text fields, or press the mic. Speech
 * streams to the transcription vendor with a 60 s token minted on first use (never on page load);
 * without one the clip is recorded and transcribed after release. The server interprets and
 * validates; this component only performs what came back.
 */
export function VoiceCopilot() {
  const navigate = useNavigate();
  const location = useLocation();
  const [phase, setPhase] = useState<Phase>("idle");
  const [notice, setNotice] = useState<Notice>(null);
  const [partial, setPartial] = useState("");
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [failures, setFailures] = useState(0);
  const history = useRef<{ role: "user" | "copilot"; content: string }[]>([]);
  const media = useRef<{ stream: MediaStream; recorder: MediaRecorder; chunks: Blob[]; live: LiveTranscriber | null } | null>(null);
  const supported = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";

  const fetchCredential = useCallback(async () => {
    const cred = (await unwrap(api.POST("/voice-commands/stream-token"))) as StreamCredential;
    return { token: JSON.stringify(cred), expires_at: new Date(cred.expires_at).getTime() };
  }, []);
  const lazy = useLazyToken("voice_copilot", fetchCredential);

  const fail = useCallback((text: string, hint?: string) => {
    setNotice({ tone: "error", text, hint });
    setPhase("done");
    setFailures((n) => {
      const next = n + 1;
      if (next >= RETRY_HINT_AFTER) setTyping(true);
      return next;
    });
  }, []);

  const perform = useCallback(
    (r: Interpret) => {
      history.current = [...history.current, { role: "copilot" as const, content: r.speak ?? r.action }].slice(-12);
      setFailures(0);
      if (r.action === "navigate" && r.target) {
        navigate(r.target === "/calls" ? callsUrl(r.params) : r.target);
        setNotice({ tone: "info", text: r.speak ?? "Done." });
      } else if (r.action === "route_to_copilot") {
        if (r.target === "analytics_chat") openAsk(r.query ?? undefined);
        setNotice({
          tone: "info",
          text: r.target === "analytics_chat" ? "Opening the analytics assistant." : "That assistant opens from its builder page.",
        });
      } else if (r.action === "ui_action" && r.target) {
        const ran = runAction(r.target, (r.params as Record<string, unknown> | null) ?? null);
        setNotice(ran ? { tone: "info", text: r.speak ?? "Done." } : { tone: "error", text: "This page can't do that any more." });
      } else if (r.action === "answer") {
        setNotice({ tone: "info", text: r.speak ?? "" });
      } else {
        if (r.highlight_element) highlight(r.highlight_element);
        setNotice({ tone: "error", text: r.speak ?? "I can't do that here.", hint: r.fallback_suggestion ?? undefined });
      }
      setPhase("done");
    },
    [navigate],
  );

  const interpret = useCallback(
    async (transcript: string) => {
      const text = transcript.trim();
      if (!text) {
        fail("Didn't catch that.", "Hold Space and speak a little longer.");
        return;
      }
      setPhase("thinking");
      setPartial(text);
      history.current = [...history.current, { role: "user" as const, content: text }].slice(-12);
      try {
        const result = (await unwrap(
          api.POST("/voice-commands/interpret", {
            body: {
              transcript: text.slice(0, 1000),
              visual_state: {
                current_route: location.pathname,
                page_title: document.title,
                current_datetime: new Date().toISOString(),
                timezone: viewerTimeZone(),
                available_actions: registeredActions() as never,
                highlightable_elements: highlightableElements(),
              },
              conversation_history: history.current.slice(0, -1),
            },
          }),
        )) as Interpret;
        perform(result);
      } catch {
        fail(navigator.onLine ? "The copilot could not answer. Try again." : "You're offline.");
      }
    },
    [fail, location.pathname, perform],
  );

  const start = useCallback(async () => {
    if (phase === "listening" || phase === "starting") return;
    setNotice(null);
    setPartial("");
    if (!navigator.onLine) {
      setNotice({ tone: "error", text: "You're offline.", hint: "Voice commands need a connection." });
      setPhase("done");
      return;
    }
    setPhase("starting");
    try {
      const perm = await navigator.permissions?.query({ name: "microphone" as PermissionName }).catch(() => null);
      if (perm?.state === "denied") throw new DOMException("denied", "NotAllowedError");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported?.("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : undefined;
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      let live: LiveTranscriber | null = null;
      try {
        live = await openDeepgramStream(JSON.parse(await lazy.request()) as StreamCredential, setPartial);
      } catch {
        live = null; // record now, transcribe after release
      }
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) {
          chunks.push(e.data);
          live?.send(e.data);
        }
      };
      recorder.start(250);
      media.current = { stream, recorder, chunks, live };
      setPhase("listening");
    } catch (e) {
      const blocked = e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError");
      setNotice(
        blocked
          ? { tone: "error", text: "Microphone blocked.", hint: "Allow the microphone from the icon in the address bar, or type the command." }
          : { tone: "error", text: "The microphone did not start.", hint: "Type the command instead." },
      );
      setTyping(true);
      setPhase("done");
    }
  }, [lazy, phase]);

  const stop = useCallback(async () => {
    const m = media.current;
    if (!m) return;
    media.current = null;
    setPhase("transcribing");
    const stopped = new Promise<void>((r) => (m.recorder.onstop = () => r()));
    m.recorder.stop();
    await stopped;
    m.stream.getTracks().forEach((t) => t.stop());
    let text = "";
    try {
      if (m.live) text = await m.live.finish();
      else {
        const form = new FormData();
        form.append("audio", new Blob(m.chunks, { type: "audio/webm" }), "command.webm");
        const res = (await unwrap(api.POST("/voice-commands/transcribe", { body: form as never }))) as { transcript: string };
        text = res.transcript;
      }
    } catch {
      fail("Didn't catch that.", "Try again, or type the command.");
      return;
    } finally {
      m.live?.close();
    }
    await interpret(text);
  }, [fail, interpret]);

  useEffect(() => {
    if (!supported) return;
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest("button, a, [role=button], [role=checkbox], [role=radio], [role=tab], [role=slider]")) return;
      e.preventDefault();
      void start();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || !media.current) return;
      e.preventDefault();
      void stop();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [start, stop, supported]);

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
  const status = listening ? partial || "Listening" : phase === "transcribing" ? "Transcribing" : phase === "thinking" ? `"${partial}"` : null;
  const showTypingHint = failures >= RETRY_HINT_AFTER;

  return (
    <div className="relative flex items-center gap-2">
      <AnimatePresence>
        {(status || notice || typing) && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            role="status"
            aria-live="polite"
            className="absolute bottom-[calc(100%+10px)] right-0 w-[min(320px,calc(100vw-40px))] rounded-panel border border-line bg-surface p-3 shadow-pop"
          >
            {status && (
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
                ) : (
                  <Loader2 className="size-3.5 animate-spin text-accent-text" aria-hidden />
                )}
                <span className="min-w-0 truncate">{status}</span>
              </p>
            )}
            {!status && notice && (
              <div className="flex items-start gap-2">
                {notice.text === "You're offline." ? (
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
                  maxLength={1000}
                  autoFocus
                  className={cn(
                    "h-8 min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-2.5 text-[12.5px] text-fg placeholder:text-fg-3",
                    focusRing,
                  )}
                />
                <button
                  type="submit"
                  aria-label="Send command"
                  className={cn("grad-action grid size-8 cursor-pointer place-items-center rounded-control text-white", focusRing)}
                >
                  <Send className="size-3.5" aria-hidden />
                </button>
              </form>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      <Tooltip content="Type a command">
        <button
          type="button"
          aria-label="Type a command"
          onClick={() => setTyping((t) => !t)}
          className={cn(
            "grid size-11 cursor-pointer place-items-center rounded-full border border-line bg-surface text-fg-2 shadow-pop transition-transform duration-150 hover:-translate-y-0.5 hover:text-fg",
            focusRing,
          )}
        >
          <Keyboard className="size-4" aria-hidden />
        </button>
      </Tooltip>
      {supported && (
        <Tooltip
          content={
            <span className="flex items-center gap-1.5">
              Hold <Kbd>Space</Kbd> or press to talk
            </span>
          }
        >
          <button
            type="button"
            aria-label={listening ? "Stop listening" : "Talk to the copilot"}
            aria-pressed={listening}
            onClick={() => (listening ? void stop() : void start())}
            className={cn(
              "relative grid size-11 cursor-pointer place-items-center rounded-full text-white shadow-pop transition-transform duration-150 hover:-translate-y-0.5 active:scale-95",
              listening ? "bg-on-air" : "grad-action",
              focusRing,
            )}
          >
            {listening && <span aria-hidden className="on-air-pulse absolute inset-0 rounded-full" />}
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Mic className="size-4" aria-hidden />}
          </button>
        </Tooltip>
      )}
    </div>
  );
}
