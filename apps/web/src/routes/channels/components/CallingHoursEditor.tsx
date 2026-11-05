import { Clock3, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, Panel, Select, Skeleton, SwitchControl, cn, toast } from "../../../components";
import { DAYS, DAY_LABELS, useCallingHours, useSaveCallingHours, type Day, type WeeklyWindows } from "../hooks/useOutboundCompliance";

const STARTS = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
const ENDS = [...STARTS.slice(1), "24:00"];
const DEFAULT = { start: "09:00", end: "21:00" };
const DEFAULTS = Object.fromEntries(DAYS.map((d) => [d, { ...DEFAULT }])) as WeeklyWindows;

function label(t: string) {
  if (t === "24:00") return "Midnight";
  const [h, m] = t.split(":").map(Number) as [number, number];
  const d = new Date(Date.UTC(2026, 0, 1, h, m));
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: "UTC" });
}

/** Share of the day inside the window, for the small bar under each row. */
function span(w: { start: string; end: string }) {
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
  return { left: (toMin(w.start) / 1440) * 100, width: ((toMin(w.end) - toMin(w.start)) / 1440) * 100 };
}

/**
 * Per-weekday calling hours in the recipient's local time (010 T078, FR-036). A day is either a
 * window (start before end, never across midnight) or "No calls".
 */
export function CallingHoursEditor() {
  const hours = useCallingHours();
  const save = useSaveCallingHours();
  const [draft, setDraft] = useState<WeeklyWindows | null>(null);
  useEffect(() => {
    if (hours.data) setDraft(hours.data.windows);
  }, [hours.data]);
  const dirty = useMemo(() => !!draft && !!hours.data && JSON.stringify(draft) !== JSON.stringify(hours.data.windows), [draft, hours.data]);
  const invalid = draft ? DAYS.some((d) => draft[d] && draft[d]!.start >= draft[d]!.end) : false;

  const setDay = (d: Day, value: WeeklyWindows[Day]) => setDraft((w) => (w ? { ...w, [d]: value } : w));

  return (
    <Panel
      title="Calling hours"
      description="Outbound calls only ring between these times, in the recipient's local time."
      icon={<Clock3 />}
      actions={hours.data?.is_default ? <Badge>Default</Badge> : undefined}
      bodyClassName="p-0"
    >
      {!draft ? (
        <div className="flex flex-col gap-2 p-5">
          {DAYS.map((d) => (
            <Skeleton key={d} className="h-9 w-full" />
          ))}
        </div>
      ) : (
        <>
          <ul className="divide-y divide-line">
            {DAYS.map((d) => {
              const w = draft[d];
              const bad = !!w && w.start >= w.end;
              return (
                <li
                  key={d}
                  className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-5 py-2.5 sm:grid-cols-[104px_auto_minmax(0,1fr)]"
                >
                  <span className="text-[13px] font-medium text-fg">{DAY_LABELS[d]}</span>
                  <div className="flex items-center gap-2">
                    <SwitchControl
                      aria-label={`Calls on ${DAY_LABELS[d]}`}
                      checked={!!w}
                      onCheckedChange={(on) => setDay(d, on ? { ...DEFAULT } : null)}
                    />
                    <span className={cn("w-[52px] text-[13px]", w ? "text-fg-2" : "text-fg-3")}>{w ? "Calls" : "No calls"}</span>
                  </div>
                  {w ? (
                    <div className="col-span-2 flex flex-col gap-1.5 sm:col-span-1 sm:w-fit">
                      <div className="flex items-center gap-2">
                        <Select
                          size="sm"
                          aria-label={`${DAY_LABELS[d]} start`}
                          className="w-full min-w-0 sm:w-[118px]"
                          value={w.start}
                          invalid={bad}
                          onValueChange={(start) => setDay(d, { ...w, start })}
                          options={STARTS.map((t) => ({ value: t, label: label(t) }))}
                        />
                        <span className="text-[12px] text-fg-3">to</span>
                        <Select
                          size="sm"
                          aria-label={`${DAY_LABELS[d]} end`}
                          className="w-full min-w-0 sm:w-[118px]"
                          value={w.end}
                          invalid={bad}
                          onValueChange={(end) => setDay(d, { ...w, end })}
                          options={ENDS.map((t) => ({ value: t, label: label(t) }))}
                        />
                      </div>
                      <div className="relative h-1 overflow-hidden rounded-full bg-surface-3" aria-hidden>
                        {!bad && (
                          <span
                            className="bg-accent absolute inset-y-0 rounded-full transition-[left,width] duration-300"
                            style={{ left: `${span(w).left}%`, width: `${span(w).width}%` }}
                          />
                        )}
                      </div>
                      {bad && <p className="text-[12px] text-danger-text">The start must be before the end.</p>}
                    </div>
                  ) : (
                    <span className="col-span-2 flex h-8 items-center rounded-control border border-dashed border-line px-3 text-[13px] text-fg-3 sm:col-span-1 sm:w-[268px]">
                      Blocked all day
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="flex items-center justify-between gap-2 border-t border-line px-5 py-3">
            <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden />} onClick={() => setDraft(DEFAULTS)}>
              9 am to 9 pm every day
            </Button>
            <Button
              size="sm"
              variant={dirty ? "primary" : "secondary"}
              disabled={!dirty || invalid}
              pending={save.isPending}
              onClick={() =>
                save.mutate(draft, {
                  onSuccess: () =>
                    toast({ tone: "success", title: "Calling hours saved", description: "They apply to calls requested from now on." }),
                  onError: (err) => toast({ tone: "error", title: "Not saved", description: problemMessage(err, "calling hours") }),
                })
              }
            >
              Save hours
            </Button>
          </div>
        </>
      )}
    </Panel>
  );
}
