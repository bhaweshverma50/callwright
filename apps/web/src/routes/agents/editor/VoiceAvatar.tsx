import { Pause, Play } from "lucide-react";
import type { Voice } from "../../../api/agents";
import { Badge, IconButton, cn } from "../../../components";

/** A voice's initial on a soft disc; the disc hue follows the name so lists are easy to scan. */
export function VoiceAvatar({ voice, size = "md", selected }: { voice: Pick<Voice, "name" | "voice_id">; size?: "sm" | "md"; selected?: boolean }) {
  const hue = [...voice.voice_id].reduce((n, c) => n + c.charCodeAt(0), 0) % 3;
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-display font-medium",
        size === "sm" ? "size-8 text-[13px]" : "size-10 text-[15px]",
        selected
          ? "grad-action text-white"
          : hue === 0
            ? "bg-accent-soft text-accent-text"
            : hue === 1
              ? "bg-surface-3 text-fg"
              : "bg-warning-soft text-warning-text",
      )}
    >
      {voice.name.charAt(0).toUpperCase()}
    </span>
  );
}

const GENDER: Record<string, string> = { female: "Female", male: "Male", neutral: "Neutral" };

export function VoiceTags({ voice, languageLabel }: { voice: Voice; languageLabel: (code: string) => string }) {
  const langs = voice.languages.filter((l) => l !== "multi");
  const shown = langs.slice(0, 2);
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1">
      {voice.gender && <Badge>{GENDER[voice.gender]}</Badge>}
      {shown.map((l) => (
        <Badge key={l}>{languageLabel(l)}</Badge>
      ))}
      {langs.length > shown.length && <Badge>{`${langs.length - shown.length} more`}</Badge>}
    </span>
  );
}

export function PreviewButton({ voice, playing, onToggle }: { voice: Voice; playing: boolean; onToggle: () => void }) {
  if (!voice.preview_url) return null;
  return (
    <IconButton
      label={playing ? `Stop ${voice.name} preview` : `Play ${voice.name} preview`}
      className={cn(
        "size-8 shrink-0 rounded-full border border-line-strong",
        playing && "border-transparent grad-action text-white hover:text-white",
      )}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
    >
      {playing ? <Pause className="size-3.5" aria-hidden /> : <Play className="size-3.5 translate-x-px" aria-hidden />}
    </IconButton>
  );
}
