import { Download, Pause, Play, Trash2, Hourglass, MicOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { fetchRecordingLink, type RecordingLink } from "../../api/calls";
import { isApiError } from "../../api/errors";
import { IconButton, Skeleton, cn, focusRing, toast, waveHeights } from "../../components";
import { mss } from "./format";

type State = "idle" | "loading" | "ready" | "deleted" | "processing" | "missing" | "error";

const REFRESH_EARLY_MS = 15_000;

function stateFor(e: unknown): State {
  if (isApiError(e)) {
    if (e.status === 410) return "deleted";
    if (e.status === 409) return "processing";
    if (e.status === 404) return "missing";
  }
  return "error";
}

/**
 * Call recording through a signed link of at most 10 minutes (FR-011). The link is fetched on the
 * first play, refreshed before it expires or when the storage answers with an error, and playback
 * resumes where it was (US2 scenario 2). Download asks for an attachment link named after the call.
 * `compact` is the inline list player: one round button with a progress ring.
 */
export function RecordingPlayer({
  callId,
  hasRecording,
  durationS,
  compact = false,
  processing = false,
}: {
  callId: string;
  hasRecording: boolean;
  durationS?: number | null;
  compact?: boolean;
  processing?: boolean;
}) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const link = useRef<RecordingLink | null>(null);
  const [state, setState] = useState<State>(hasRecording ? "idle" : processing ? "processing" : "missing");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(durationS ?? 0);
  const retried = useRef(false);

  useEffect(() => () => audio.current?.pause(), []);

  const ensureLink = useCallback(async (): Promise<string | null> => {
    const current = link.current;
    if (current && new Date(current.expires_at).getTime() - Date.now() > REFRESH_EARLY_MS) return current.url;
    try {
      const fresh = await fetchRecordingLink(callId);
      link.current = fresh;
      if (fresh.duration_s) setDuration(fresh.duration_s);
      return fresh.url;
    } catch (e) {
      setState(stateFor(e));
      return null;
    }
  }, [callId]);

  const play = useCallback(async () => {
    setState((s) => (s === "idle" ? "loading" : s));
    const url = await ensureLink();
    if (!url) return;
    let el = audio.current;
    if (!el) {
      el = new Audio();
      el.preload = "auto";
      el.ontimeupdate = () => setTime(el!.currentTime);
      el.onloadedmetadata = () => Number.isFinite(el!.duration) && setDuration(el!.duration);
      el.onended = () => setPlaying(false);
      el.onpause = () => setPlaying(false);
      el.onplay = () => setPlaying(true);
      el.onerror = () => {
        // An expired or revoked link: get a fresh one once and resume at the same second.
        if (retried.current) {
          setState("error");
          return;
        }
        retried.current = true;
        const at = el!.currentTime;
        link.current = null;
        void ensureLink().then((fresh) => {
          if (!fresh) return;
          el!.src = fresh;
          el!.currentTime = at;
          void el!.play().catch(() => setState("error"));
        });
      };
      audio.current = el;
    }
    if (el.src !== url) {
      const at = el.currentTime;
      el.src = url;
      if (at) el.currentTime = at;
    }
    setState("ready");
    try {
      await el.play();
      retried.current = false;
    } catch {
      /* the error handler above takes over */
    }
  }, [ensureLink]);

  const toggle = () => {
    if (playing) audio.current?.pause();
    else void play();
  };

  const seekTo = (fraction: number) => {
    const el = audio.current;
    const total = duration || el?.duration || 0;
    if (!total) return;
    const at = Math.max(0, Math.min(total, fraction * total));
    setTime(at);
    if (el) el.currentTime = at;
    else void play().then(() => audio.current && (audio.current.currentTime = at));
  };

  const download = async () => {
    try {
      const l = await fetchRecordingLink(callId, "attachment");
      const a = document.createElement("a");
      a.href = l.url;
      a.download = l.filename;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      setState(stateFor(e));
      toast({ tone: "error", title: "Download failed", description: "The recording could not be fetched. Try again in a moment." });
    }
  };

  const unavailable = state === "deleted" || state === "processing" || state === "missing";
  const progress = duration ? Math.min(1, time / duration) : 0;

  if (compact) {
    if (unavailable) {
      return (
        <span className="inline-flex items-center gap-1.5 text-[12px] text-fg-3">
          {state === "processing" ? <Hourglass className="size-3.5" aria-hidden /> : <MicOff className="size-3.5" aria-hidden />}
          {state === "processing" ? "Finishing" : state === "deleted" ? "Deleted" : "None"}
        </span>
      );
    }
    const r = 13;
    const c = 2 * Math.PI * r;
    return (
      <span className="inline-flex items-center gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            toggle();
          }}
          aria-label={playing ? "Pause recording" : "Play recording"}
          className={cn(
            "group/play relative grid size-8 cursor-pointer place-items-center rounded-full bg-accent-soft text-accent-text transition-transform duration-150 hover:scale-105 active:scale-95",
            focusRing,
          )}
        >
          <svg viewBox="0 0 32 32" className="absolute inset-0 -rotate-90" aria-hidden>
            <circle cx="16" cy="16" r={r} fill="none" stroke="currentColor" strokeOpacity="0.18" strokeWidth="2" />
            <circle
              cx="16"
              cy="16"
              r={r}
              fill="none"
              stroke="url(#rec-ring)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={c}
              strokeDashoffset={c * (1 - progress)}
              className="transition-[stroke-dashoffset] duration-200"
            />
            <defs>
              <linearGradient id="rec-ring" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0" stopColor="var(--heat-1)" />
                <stop offset="1" stopColor="var(--heat-2)" />
              </linearGradient>
            </defs>
          </svg>
          {state === "loading" ? (
            <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />
          ) : playing ? (
            <Pause className="size-3.5" aria-hidden fill="currentColor" />
          ) : (
            <Play className="ml-0.5 size-3.5" aria-hidden fill="currentColor" />
          )}
        </button>
        {(playing || time > 0) && <span className="font-mono text-[11.5px] text-fg-3 tnum">{mss(time)}</span>}
      </span>
    );
  }

  if (unavailable) {
    const copy = {
      deleted: { icon: Trash2, title: "Recording deleted under your retention policy", body: "The transcript and call details are kept." },
      processing: { icon: Hourglass, title: "Recording is being finalised", body: "It is ready a few seconds after the call ends." },
      missing: { icon: MicOff, title: "No recording for this call", body: "Recording was off for this call, or the call never connected." },
    }[state];
    const Icon = copy.icon;
    return (
      <div className="flex items-center gap-3 rounded-panel border border-dashed border-line-strong bg-surface-2/60 px-4 py-3.5">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-3 text-fg-3">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-fg">{copy.title}</p>
          <p className="text-[12.5px] text-fg-3">{copy.body}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 rounded-panel border border-line bg-surface px-3 py-2.5 shadow-1">
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "Pause recording" : "Play recording"}
        className={cn(
          "grad-action grid size-10 shrink-0 cursor-pointer place-items-center rounded-full text-white shadow-1 transition-transform duration-150 hover:scale-105 active:scale-95",
          focusRing,
        )}
      >
        {state === "loading" ? (
          <span className="size-4 animate-spin rounded-full border-2 border-white border-t-transparent" aria-hidden />
        ) : playing ? (
          <Pause className="size-4" aria-hidden fill="currentColor" />
        ) : (
          <Play className="ml-0.5 size-4" aria-hidden fill="currentColor" />
        )}
      </button>
      <SeekWave progress={progress} onSeek={seekTo} playing={playing} seed={callId.length + callId.charCodeAt(callId.length - 1)} />
      <span className="shrink-0 whitespace-nowrap text-right font-mono text-[12px] text-fg-2 tnum sm:w-[86px]">
        {mss(time)} / {duration ? mss(duration) : "--:--"}
      </span>
      <IconButton label="Download recording" onClick={() => void download()}>
        <Download className="size-4" aria-hidden />
      </IconButton>
      {state === "error" && (
        <span role="status" className="sr-only">
          The recording could not be played.
        </span>
      )}
    </div>
  );
}

/** A waveform you can click or drag to seek; played bars take the heat ramp. */
function SeekWave({ progress, onSeek, playing, seed }: { progress: number; onSeek: (f: number) => void; playing: boolean; seed: number }) {
  const heights = waveHeights(72, seed);
  const ref = useRef<HTMLDivElement>(null);
  const at = (e: PointerEvent<HTMLDivElement>) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    onSeek((e.clientX - box.left) / box.width);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight") onSeek(Math.min(1, progress + 0.05));
    if (e.key === "ArrowLeft") onSeek(Math.max(0, progress - 0.05));
  };
  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(progress * 100)}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture?.(e.pointerId);
        at(e);
      }}
      onPointerMove={(e) => e.buttons === 1 && at(e)}
      onKeyDown={onKey}
      className={cn(
        "flex h-9 min-w-0 flex-1 cursor-pointer items-center gap-[2px] overflow-hidden rounded-inline max-sm:[&>span:nth-child(even)]:hidden",
        focusRing,
      )}
    >
      {heights.map((h, i) => {
        const played = i / heights.length < progress;
        return (
          <span
            key={i}
            aria-hidden
            className={cn(
              "min-w-0 flex-1 rounded-full transition-colors duration-150",
              played ? "" : "bg-line-strong",
              playing && played && "opacity-95",
            )}
            style={{
              height: `${Math.max(14, h * 100)}%`,
              background: played ? `linear-gradient(180deg, var(--heat-1), var(--heat-2) 60%, var(--heat-3))` : undefined,
            }}
          />
        );
      })}
    </div>
  );
}

export function RecordingPlayerSkeleton() {
  return <Skeleton className="h-[58px] w-full rounded-panel" />;
}
