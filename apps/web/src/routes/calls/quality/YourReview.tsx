import { useQueryClient } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp, Users } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { callKeys } from "../../../api/calls";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { deleteMyAnnotation, putMyAnnotation, qualityKeys, useAnnotations, type Annotation } from "../../../api/quality";
import { Badge, Button, ConfirmDialog, Skeleton, Textarea, cn, focusRing, toast } from "../../../components";
import { when } from "../format";

export const NOTE_LIMIT = 2000;
type Label = "good" | "bad";

function Thumb({ label, active, disabled, onClick }: { label: Label; active: boolean; disabled: boolean; onClick: () => void }) {
  const Icon = label === "good" ? ThumbsUp : ThumbsDown;
  const text = label === "good" ? "Good" : "Bad";
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "relative inline-flex h-10 flex-1 cursor-pointer items-center justify-center gap-2 overflow-hidden rounded-control border text-[13px] font-medium transition-[background-color,border-color,color,box-shadow] duration-200 sm:flex-none sm:px-5",
        active
          ? label === "good"
            ? "border-success bg-success-soft text-success-text shadow-[0_0_0_3px_var(--success-soft)]"
            : "border-danger bg-danger-soft text-danger-text shadow-[0_0_0_3px_var(--danger-soft)]"
          : "border-line-strong bg-surface text-fg-2 hover:border-fg-3 hover:text-fg",
        "disabled:cursor-not-allowed disabled:opacity-60",
        focusRing,
      )}
    >
      <motion.span
        key={String(active)}
        initial={active ? { scale: 0.5, rotate: label === "good" ? -20 : 20 } : false}
        animate={{ scale: 1, rotate: 0 }}
        transition={{ type: "spring", stiffness: 480, damping: 16 }}
      >
        <Icon className="size-4" fill={active ? "currentColor" : "none"} fillOpacity={0.18} aria-hidden />
      </motion.span>
      {text}
    </button>
  );
}

function OtherLabel({ a }: { a: Annotation }) {
  return (
    <li className="flex items-start gap-2.5 py-2">
      <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent-text">
        {a.user.display_name
          .split(/\s+/)
          .map((p) => p[0])
          .join("")
          .slice(0, 2)
          .toUpperCase()}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="font-medium text-fg">{a.user.display_name}</span>
          <Badge tone={a.label === "good" ? "success" : "danger"}>{a.label === "good" ? "Good" : "Bad"}</Badge>
          <span className="text-fg-3">{when(a.updated_at)}</span>
        </span>
        {a.note && <p className="text-[12.5px] leading-relaxed text-fg-2">{a.note}</p>}
      </div>
    </li>
  );
}

/**
 * "Your review" (US3, T047): thumbs up or down with an optional note, one label per person per
 * call. Clicking the active thumb removes the label (after a confirmation when a note would be
 * lost). Teammates' labels show with their names.
 */
export function YourReview({ callId, onLabelled }: { callId: string; onLabelled?: (label: Label | null) => void }) {
  const qc = useQueryClient();
  const ann = useAnnotations(callId);
  const mine = ann.data?.mine ?? null;
  const [note, setNote] = useState<string | null>(null);
  const [lastMine, setLastMine] = useState<Annotation | null>(mine);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (mine !== lastMine) {
    setLastMine(mine);
    setNote(null);
  }
  const savedNote = mine?.note ?? "";
  const text = note ?? savedNote;
  const noteDirty = note !== null && note !== savedNote;
  const tooLong = text.length > NOTE_LIMIT;
  const others = (ann.data?.items ?? []).filter((a) => a.id !== mine?.id);

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: qualityKeys.annotations(callId) });
    void qc.invalidateQueries({ queryKey: qualityKeys.review });
    void qc.invalidateQueries({ queryKey: qualityKeys.calibration });
    void qc.invalidateQueries({ queryKey: callKeys.all });
  };

  const put = async (label: Label, withNote: string) => {
    setBusy(true);
    setError(null);
    try {
      await putMyAnnotation(callId, label, withNote.trim() ? withNote : null);
      await refresh();
      setNote(null);
      onLabelled?.(label);
    } catch (e) {
      setError(
        isApiError(e) && e.status === 422
          ? (e.problem.errors?.[0]?.message ?? `Keep the note under ${NOTE_LIMIT.toLocaleString("en-US")} characters.`)
          : problemMessage(e, "call"),
      );
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      await deleteMyAnnotation(callId);
      setConfirm(false);
      await refresh();
      setNote(null);
      onLabelled?.(null);
    } catch (e) {
      toast({ tone: "error", title: "Could not remove your label", description: problemMessage(e, "call") });
    } finally {
      setBusy(false);
    }
  };

  const press = (label: Label) => {
    if (mine?.label === label) {
      if (mine.note) setConfirm(true);
      else void clear();
    } else void put(label, text);
  };

  return (
    <section aria-labelledby="review-h" className="flex flex-col gap-3 rounded-panel border border-line bg-surface-2/40 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="review-h" className="text-[13.5px] font-semibold text-fg">
          Your review
        </h3>
        <span className="text-[12px] text-fg-3">Labels calibrate the automatic checks.</span>
      </div>
      {ann.isPending ? (
        <Skeleton className="h-10 w-56" />
      ) : (
        <>
          <div className="flex gap-2" role="group" aria-label="Your label">
            <Thumb label="good" active={mine?.label === "good"} disabled={busy} onClick={() => press("good")} />
            <Thumb label="bad" active={mine?.label === "bad"} disabled={busy} onClick={() => press("bad")} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`note-${callId}`} className="flex items-baseline justify-between text-[12.5px] text-fg-3">
              <span>Note {mine ? "" : "(saved with your label)"}</span>
              <span className={cn("font-mono tnum", tooLong && "text-danger-text")}>
                {text.length.toLocaleString("en-US")}/{NOTE_LIMIT.toLocaleString("en-US")}
              </span>
            </label>
            <Textarea
              id={`note-${callId}`}
              value={text}
              aria-invalid={tooLong}
              placeholder={mine ? "What made this call good or bad?" : "Optional. Pick a label to save it."}
              className="min-h-16 bg-surface"
              onChange={(e) => setNote(e.target.value)}
            />
            {tooLong && (
              <p role="alert" className="text-[12.5px] text-danger-text">
                Keep the note under 2,000 characters.
              </p>
            )}
            {error && (
              <p role="alert" className="text-[12.5px] text-danger-text">
                {error}
              </p>
            )}
            <AnimatePresence initial={false}>
              {mine && noteDirty && (
                <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex justify-end gap-2">
                  <Button size="sm" onClick={() => setNote(null)} disabled={busy}>
                    Discard
                  </Button>
                  <Button size="sm" variant="primary" pending={busy} disabled={tooLong} onClick={() => void put(mine.label, text)}>
                    Save note
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          {mine && (
            <p className="text-[12px] text-fg-3" aria-live="polite">
              You labelled this call {mine.label === "good" ? "Good" : "Bad"} {when(mine.updated_at)}. Click it again to remove the label.
            </p>
          )}
          {others.length > 0 && (
            <div className="border-t border-line pt-2">
              <p className="flex items-center gap-1.5 text-[12px] text-fg-3">
                <Users className="size-3.5" aria-hidden /> Teammates
              </p>
              <ul className="divide-y divide-line">
                {others.map((a) => (
                  <OtherLabel key={a.id} a={a} />
                ))}
              </ul>
            </div>
          )}
        </>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        tone="danger"
        title="Remove your label and note?"
        description="Your note on this call is deleted with the label."
        confirmLabel="Remove label"
        pending={busy}
        onConfirm={() => void clear()}
      />
    </section>
  );
}
