import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileAudio, Music4, Pause, Play, Trash2, Upload, Volume1 } from "lucide-react";
import { useRef } from "react";
import { agentKeys, deleteAmbientAudio, useAmbientAudio, type AmbientAudioFile } from "../../../api/agents";
import { postForm } from "../../../api/client";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Button, FieldRow, IconButton, Select, SwitchControl, TruncatedText, toast } from "../../../components";
import type { Catalogs } from "./catalogs";
import { controlFor, FieldError, SliderRow } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { usePreview } from "./usePreview";
import { fieldId, fieldLabel } from "../config/fields";
import { operationExtensions } from "../../../lib/contract.gen";

const ACCEPT = ".mp3,.wav,.ogg,.flac,.aac,.opus";
const UPLOAD = operationExtensions["POST /voices/ambient-audio"];
const MAX_BYTES = UPLOAD["x-max-file-bytes"];
const MAX_MB = MAX_BYTES / (1024 * 1024);

const UPLOAD_ERRORS: Record<number, string> = {
  409: `You already have ${UPLOAD["x-max-uploads"]} uploads. Delete one to add another.`,
  413: `That file is larger than ${MAX_MB} MB.`,
  415: "Use an mp3, wav, ogg, flac, aac or opus file.",
};

function upload(file: File) {
  const form = new FormData();
  form.append("file", file);
  return postForm("/voices/ambient-audio", form);
}

function sizeLabel(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/**
 * Background audio (T043, FR-012): built-in ambience or the workspace's own uploads (common audio
 * formats, size-limited), with a preview and a volume shown as percent of normal (0.8 is 80%).
 */
export function BackgroundAudioField({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const bg = draft.config.advanced.background_audio;
  const qc = useQueryClient();
  const uploads = useAmbientAudio();
  const preview = usePreview();
  const input = useRef<HTMLInputElement>(null);
  const items = uploads.data?.items ?? [];
  const src = bg.source;
  const value = !src ? undefined : src.kind === "builtin" ? `builtin:${src.id}` : `upload:${src.key}`;
  const selectedPreview =
    src?.kind === "builtin"
      ? catalogs.voice.ambient_sounds.find((s) => s.id === src.id)?.preview_url
      : src
        ? items.find((u) => u.key === src.key)?.preview_url
        : null;

  const add = useMutation({
    mutationFn: upload,
    onSuccess: (file) => {
      qc.setQueryData<{ items: AmbientAudioFile[] }>(agentKeys.ambient, (old) => ({ items: [...(old?.items ?? []), file] }));
      draft.update((c) => void (c.advanced.background_audio.source = { kind: "upload", key: file.key }));
      toast({ tone: "success", title: "Sound uploaded", description: file.filename });
    },
    onError: (e) =>
      toast({
        tone: "error",
        title: "Upload failed",
        description: isApiError(e) ? (UPLOAD_ERRORS[e.status] ?? problemMessage(e)) : problemMessage(e),
      }),
  });
  const remove = useMutation({
    mutationFn: deleteAmbientAudio,
    onSuccess: (_d, key) => {
      qc.setQueryData<{ items: AmbientAudioFile[] }>(agentKeys.ambient, (old) => ({ items: (old?.items ?? []).filter((u) => u.key !== key) }));
      toast({ tone: "success", title: "Sound deleted" });
    },
    onError: (e) =>
      toast({
        tone: "error",
        title: "Sound not deleted",
        description: isApiError(e) && e.status === 409 ? "An agent still uses this sound. Choose another sound there first." : problemMessage(e),
      }),
  });

  const sourceId = fieldId("/advanced/background_audio/source");
  return (
    <>
      <FieldRow
        inline
        icon={<Music4 />}
        label={fieldLabel("/advanced/background_audio/enabled")}
        htmlFor={fieldId("/advanced/background_audio/enabled")}
        description="Plays a quiet sound under the call, such as office ambience."
      >
        <SwitchControl
          id={fieldId("/advanced/background_audio/enabled")}
          checked={bg.enabled}
          onCheckedChange={(on) =>
            draft.update((c) => {
              c.advanced.background_audio.enabled = on;
              if (on && !c.advanced.background_audio.source)
                c.advanced.background_audio.source = { kind: "builtin", id: catalogs.voice.ambient_sounds[0]?.id ?? "office_ambience" };
            })
          }
        />
      </FieldRow>
      {bg.enabled && (
        <>
          <FieldRow
            icon={<FileAudio />}
            label={fieldLabel("/advanced/background_audio/source")}
            htmlFor={sourceId}
            description={`Built-in sounds, or your own file (mp3, wav, ogg, flac, aac or opus, up to ${MAX_MB} MB).`}
          >
            <div className="flex w-full items-center gap-2">
              <Select
                id={sourceId}
                className="min-w-0 flex-1"
                value={value}
                placeholder="Choose a sound"
                invalid={Boolean(draft.errorFor("/advanced/background_audio/source"))}
                onValueChange={(v) => {
                  const [kind, ref = ""] = [v.slice(0, v.indexOf(":")), v.slice(v.indexOf(":") + 1)];
                  draft.update(
                    (c) =>
                      void (c.advanced.background_audio.source = kind === "builtin" ? { kind: "builtin", id: ref } : { kind: "upload", key: ref }),
                  );
                  draft.touch("/advanced/background_audio/source");
                }}
                groups={[
                  { label: "Built-in sounds", options: catalogs.voice.ambient_sounds.map((s) => ({ value: `builtin:${s.id}`, label: s.label })) },
                  ...(items.length ? [{ label: "Your uploads", options: items.map((u) => ({ value: `upload:${u.key}`, label: u.filename })) }] : []),
                ]}
              />
              {selectedPreview && (
                <IconButton
                  label={preview.playing === value ? "Stop preview" : "Play preview"}
                  className="size-9 shrink-0 rounded-full border border-line-strong"
                  onClick={() => preview.toggle(value!, selectedPreview)}
                >
                  {preview.playing === value ? <Pause className="size-3.5" aria-hidden /> : <Play className="size-3.5 translate-x-px" aria-hidden />}
                </IconButton>
              )}
            </div>
            <FieldError message={draft.errorFor("/advanced/background_audio/source")} />
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              aria-hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                if (file.size > MAX_BYTES) return void toast({ tone: "error", title: "Upload failed", description: UPLOAD_ERRORS[413] });
                add.mutate(file);
              }}
            />
            <Button size="sm" variant="ghost" icon={<Upload aria-hidden />} pending={add.isPending} onClick={() => input.current?.click()}>
              Upload a sound
            </Button>
          </FieldRow>
          {items.length > 0 && (
            <div className="px-5 py-3">
              <p className="mb-2 text-[13px] font-medium text-fg-2">Your uploads</p>
              <ul className="flex flex-col gap-1.5">
                {items.map((u) => (
                  <li key={u.key} className="flex items-center gap-3 rounded-control bg-surface-2/60 px-3 py-1.5">
                    <FileAudio className="size-4 shrink-0 text-fg-3" aria-hidden />
                    <TruncatedText className="min-w-0 flex-1 text-[13px] text-fg">{u.filename}</TruncatedText>
                    <span className="shrink-0 font-mono text-[12px] text-fg-3 tnum">{sizeLabel(u.size_bytes)}</span>
                    <IconButton
                      label={`Delete ${u.filename}`}
                      className="size-8"
                      pending={remove.isPending && remove.variables === u.key}
                      onClick={() => remove.mutate(u.key)}
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </IconButton>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <SliderRow
            draft={draft}
            control={controlFor(catalogs.voice.controls, "/advanced/background_audio/volume")}
            pointer="/advanced/background_audio/volume"
            icon={<Volume1 />}
            description="100% is the sound's normal loudness."
            value={bg.volume ?? 0.8}
            marks={[
              { value: 0, label: "0%" },
              { value: 1, label: "100%" },
              { value: 2, label: "200%" },
              { value: 3, label: "300%" },
            ]}
            onChange={(v) => draft.update((c) => void (c.advanced.background_audio.volume = v))}
          />
        </>
      )}
    </>
  );
}
