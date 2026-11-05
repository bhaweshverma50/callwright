import { PhoneOutgoing } from "@phosphor-icons/react";
import { Ban, CalendarClock, CalendarX, CircleAlert, Loader2, PhoneForwarded } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useCallCallbacks, useCancelCallback, type Callback, type CallbackStatus } from "../../../api/callbacks";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, ConfirmDialog, cn, toast } from "../../../components";
import { CALLBACK_STATUS_LABELS, CALLBACK_STATUS_TONES, callDrawerSearch, failureText, localTimeLabel, phoneLabel, zoneLabel } from "./format";

const STATUS_ICONS: Record<CallbackStatus, typeof CalendarClock> = {
  scheduled: CalendarClock,
  placing: Loader2,
  placed: PhoneForwarded,
  failed: CircleAlert,
  cancelled: Ban,
};

export function CallbackStatusBadge({ status }: { status: CallbackStatus }) {
  const Icon = STATUS_ICONS[status];
  return (
    <Badge tone={CALLBACK_STATUS_TONES[status]} icon={<Icon className={cn(status === "placing" && "animate-spin")} aria-hidden />}>
      {CALLBACK_STATUS_LABELS[status]}
    </Badge>
  );
}

/** The recipient's zone as a short tag ("EDT"); the full IANA name is in the title and read out. */
export function ZoneTag({ callback, className }: { callback: Pick<Callback, "timezone" | "scheduled_at">; className?: string }) {
  const label = zoneLabel(callback.timezone, callback.scheduled_at);
  return (
    <span
      title={`Recipient's time zone: ${callback.timezone}`}
      className={cn(
        "inline-flex h-[18px] items-center rounded-inline border border-line bg-surface-2 px-1.5 align-[1px] font-mono text-[11px] font-medium leading-none text-fg-3",
        className,
      )}
    >
      <span aria-hidden>{label}</span>
      <span className="sr-only">{`${label}, ${callback.timezone}`}</span>
    </span>
  );
}

/** The scheduled time in the recipient's zone, with its zone tag. */
export function CallbackTime({ callback, className, nowrap }: { callback: Callback; className?: string; nowrap?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-x-1.5 gap-y-0.5", nowrap ? "whitespace-nowrap" : "flex-wrap", className)}>
      <time dateTime={callback.scheduled_at} className="whitespace-nowrap">
        {localTimeLabel(callback)}
      </time>
      <ZoneTag callback={callback} />
    </span>
  );
}

/** Confirms and cancels one scheduled callback, then reports the outcome in a toast. */
export function CancelCallbackDialog({ callback: open, onClose }: { callback: Callback | null; onClose: () => void }) {
  const cancel = useCancelCallback();
  // Keep the last callback while the dialog animates closed.
  const [last, setLast] = useState(open);
  if (open && open !== last) setLast(open);
  const callback = open ?? last;
  const when = callback ? `${localTimeLabel(callback)} ${zoneLabel(callback.timezone, callback.scheduled_at)}` : "";
  const run = () => {
    if (!callback) return;
    cancel.mutate(callback.id, {
      onSuccess: () =>
        toast({ tone: "success", title: "Callback cancelled", description: `${phoneLabel(callback.to_number)} will not be called on ${when}.` }),
      onError: (e) =>
        toast({
          tone: "error",
          title: isApiError(e) && e.status === 409 ? "This callback can no longer be cancelled" : "The callback was not cancelled",
          description:
            isApiError(e) && e.status === 409
              ? "It is already being placed, was placed, or failed. The list now shows where it stands."
              : problemMessage(e, "callback"),
        }),
      onSettled: onClose,
    });
  };
  return (
    <ConfirmDialog
      open={Boolean(open)}
      onOpenChange={(o) => !o && !cancel.isPending && onClose()}
      icon={<CalendarX aria-hidden />}
      title="Cancel this callback?"
      description={
        callback ? (
          <>
            The call to <span className="whitespace-nowrap font-mono text-fg tnum">{phoneLabel(callback.to_number)}</span> on{" "}
            <span className="whitespace-nowrap">{when}</span> will not be placed. The caller is not told.
          </>
        ) : undefined
      }
      cancelLabel="Keep it"
      confirmLabel="Cancel callback"
      tone="danger"
      pending={cancel.isPending}
      onConfirm={run}
    />
  );
}

const CHIP_TONES: Record<CallbackStatus, string> = {
  scheduled: "bg-accent-soft text-accent-text",
  placing: "bg-accent-soft text-accent-text",
  placed: "bg-success-soft text-success-text",
  failed: "bg-danger-soft text-danger-text",
  cancelled: "bg-surface-3 text-fg-3",
};

function headline(cb: Callback) {
  const time = <CallbackTime callback={cb} className="font-medium text-fg" />;
  switch (cb.status) {
    case "scheduled":
      return <>Callback scheduled for {time}</>;
    case "placing":
      return <>Calling back now, for {time}</>;
    case "placed":
      return <>Called back {time}</>;
    case "failed":
      return <>Callback for {time} was not placed</>;
    case "cancelled":
      return <>Callback for {time} was cancelled</>;
  }
}

/** One callback booked on this call: when, to whom, the agent's note, and what became of it. */
export function CallbackCard({ callback: cb, onCancel }: { callback: Callback; onCancel: (cb: Callback) => void }) {
  const [params] = useSearchParams();
  return (
    <div className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3.5 shadow-1">
      <span className={cn("grid size-7 shrink-0 place-items-center rounded-control", CHIP_TONES[cb.status])} aria-hidden>
        <PhoneOutgoing className="size-3.5" weight="bold" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
          <p className="min-w-0 text-[14px] leading-relaxed text-fg-2">{headline(cb)}</p>
          <CallbackStatusBadge status={cb.status} />
        </div>
        <p className="text-[13px] text-fg-3">
          To <span className="whitespace-nowrap font-mono text-fg-2 tnum">{phoneLabel(cb.to_number)}</span> from{" "}
          <span className="whitespace-nowrap font-mono text-fg-2 tnum">{phoneLabel(cb.from_number)}</span>
          {cb.agent_name && (
            <>
              <span aria-hidden className="px-1.5 text-fg-3/60">
                /
              </span>
              <span className="text-fg-2">{cb.agent_name}</span>
            </>
          )}
        </p>
        {cb.note && <p className="mt-0.5 text-[13px] leading-relaxed text-fg">{cb.note}</p>}
        {cb.status === "failed" && <p className="text-[13px] text-danger-text">{failureText(cb)}</p>}
        {(cb.status === "scheduled" || (cb.status === "placed" && cb.call_id)) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-3">
            {cb.status === "scheduled" && (
              <Button size="sm" variant="secondary" icon={<CalendarX aria-hidden />} onClick={() => onCancel(cb)}>
                Cancel callback
              </Button>
            )}
            {cb.status === "placed" && cb.call_id && (
              <Link to={callDrawerSearch(params, cb.call_id)} className="link-underline text-[13px] font-medium text-accent-text">
                Open the callback call
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Callbacks booked on a call, for its drawer. Renders nothing when there are none. */
export function CallCallbacks({ callId }: { callId: string }) {
  const callbacks = useCallCallbacks(callId);
  const [cancelling, setCancelling] = useState<Callback | null>(null);
  const items = callbacks.data ?? [];
  if (!items.length) return null;
  return (
    <section aria-label="Callbacks" className="flex flex-col gap-2">
      {items.map((cb) => (
        <CallbackCard key={cb.id} callback={cb} onCancel={setCancelling} />
      ))}
      <CancelCallbackDialog callback={cancelling} onClose={() => setCancelling(null)} />
    </section>
  );
}
