/**
 * Calls on air: the dashboard's "Live now" card, the pinned rows on Call History and the ticking
 * duration used wherever a live call shows. All of them read the one shared live query
 * (`api/live.ts`), so the badge, the card and the strip never disagree.
 */
import { Bot, Phone, User } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { useLiveCalls, type LiveCall } from "../../../api/live";
import { Badge, Button, OnAir, TruncatedText, Waveform, cn, focusRing } from "../../../components";
import { CHANNEL_ICONS } from "../columns";
import { phone } from "../format";
import { LiveDuration } from "./LiveDuration";

/** Who is on the line, as people say it: the outside number, or a browser call. */
export function liveParty(c: Pick<LiveCall, "channel" | "direction" | "from_number" | "to_number">): string {
  if (c.channel === "web") return "Browser call";
  const outside = c.direction === "outbound" ? c.to_number : c.from_number;
  return phone(outside) || (c.direction === "outbound" ? "Outbound call" : "Unknown caller");
}

function liveContext(c: LiveCall): string {
  const ringing = c.status !== "in_progress";
  if (c.channel === "web") return ringing ? `Connecting to ${c.agent.name}` : `Talking to ${c.agent.name}`;
  if (c.direction === "outbound") return ringing ? `${c.agent.name} is calling` : `${c.agent.name} called out`;
  return ringing ? `Ringing ${c.agent.name}` : `Answered by ${c.agent.name}`;
}

/** The channel glyph; while ringing, the phone rocks and two rings spread from it. */
function CallGlyph({ call }: { call: LiveCall }) {
  const reduce = useReducedMotion();
  const ringing = call.status !== "in_progress";
  const Icon = ringing ? Phone : CHANNEL_ICONS[call.channel];
  return (
    <span className="relative grid size-9 shrink-0 place-items-center" aria-hidden>
      {ringing &&
        !reduce &&
        [0, 0.5].map((delay) => (
          <motion.span
            key={delay}
            className="absolute inset-0 rounded-full border border-accent/50"
            initial={{ scale: 0.7, opacity: 0 }}
            animate={{ scale: [0.7, 1.35], opacity: [0.8, 0] }}
            transition={{ duration: 1.2, delay, repeat: Infinity, repeatDelay: 0.8, ease: "easeOut" }}
          />
        ))}
      <motion.span
        className={cn(
          "relative grid size-9 place-items-center rounded-full",
          ringing ? "bg-accent text-accent-fg shadow-1" : "bg-accent-soft text-accent-text",
        )}
        animate={ringing && !reduce ? { rotate: [0, -12, 10, -8, 6, 0, 0] } : { rotate: 0 }}
        transition={ringing && !reduce ? { duration: 2, times: [0, 0.05, 0.1, 0.15, 0.2, 0.25, 1], repeat: Infinity } : { duration: 0.2 }}
      >
        <Icon className="size-4" strokeWidth={1.9} />
      </motion.span>
    </span>
  );
}

function LastLine({ call }: { call: LiveCall }) {
  if (call.status !== "in_progress") {
    return <span className="text-[13px] text-fg-3">Waiting for an answer</span>;
  }
  const m = call.last_message;
  if (!m) return <span className="text-[13px] text-fg-3">Connected, nobody has spoken yet</span>;
  const Who = m.role === "user" ? User : Bot;
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-[13px] text-fg-2">
      <Who className="size-3.5 shrink-0 text-fg-3" aria-label={m.role === "user" ? "Caller" : "Agent"} />
      <TruncatedText focusable={false}>{m.text}</TruncatedText>
    </span>
  );
}

/** One call on air. The whole row opens the call (drawer with the live transcript). */
export function LiveCallRow({ call, onOpen }: { call: LiveCall; onOpen: (id: string) => void }) {
  const live = call.status === "in_progress";
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4, transition: { duration: 0.16 } }}
      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
    >
      <button
        type="button"
        onClick={() => onOpen(call.call_id)}
        aria-label={`${liveParty(call)}, ${liveContext(call)}. Open the call`}
        className={cn(
          "group grid w-full cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-1.5 px-4 py-3 text-left transition-colors duration-150 sm:px-5",
          "hover:bg-[color-mix(in_srgb,var(--accent-soft)_45%,var(--surface))] md:grid-cols-[auto_minmax(0,14rem)_minmax(0,1fr)_auto]",
          focusRing,
        )}
      >
        <CallGlyph call={call} />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className={cn("truncate text-[14px] font-medium text-fg", call.channel !== "web" && "font-mono text-[13px] tnum")}>
              {liveParty(call)}
            </span>
            {call.origin === "test" && <Badge>Test</Badge>}
          </span>
          <span className="truncate text-[13px] text-fg-3">{liveContext(call)}</span>
        </span>
        <span className="col-span-3 col-start-1 row-start-2 min-w-0 pl-[3.125rem] md:col-span-1 md:col-start-3 md:row-start-1 md:pl-0">
          <LastLine call={call} />
        </span>
        <span className="col-start-3 row-start-1 flex items-center gap-2.5 md:col-start-4">
          {live ? (
            <>
              <Waveform
                live
                bars={11}
                seed={call.call_id.length + call.call_id.charCodeAt(call.call_id.length - 1)}
                height={18}
                className="hidden w-[52px] sm:block"
              />
              <LiveDuration since={call.connected_at} className="min-w-[3.25rem] text-right text-[14px] font-semibold text-fg" />
            </>
          ) : (
            <span className="text-[13px] font-medium text-accent-text">Ringing</span>
          )}
        </span>
      </button>
    </motion.li>
  );
}

export function LiveCallList({ calls, onOpen, label }: { calls: LiveCall[]; onOpen: (id: string) => void; label: string }) {
  return (
    <ul className="divide-y divide-line" aria-label={label}>
      <AnimatePresence initial={false}>
        {calls.map((c) => (
          <LiveCallRow key={c.call_id} call={c} onOpen={onOpen} />
        ))}
      </AnimatePresence>
    </ul>
  );
}

function CardHeader({ count, children }: { count: number; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-3 sm:px-5">
      <OnAir label={<span className="text-[14px] font-semibold text-fg">Live now</span>} />
      <span className="text-[13px] text-fg-3" aria-live="polite">
        <span className="font-mono tnum">{count}</span> {count === 1 ? "call" : "calls"}
      </span>
      {children}
    </header>
  );
}

/**
 * Dashboard "Live now": appears the moment a call rings, with each call's party, agent, latest
 * line and a ticking duration. With nothing on air it is one quiet line, so the page does not jump.
 * Hidden while loading or when the endpoint is unavailable.
 */
export function LiveNowCard({ onOpen }: { onOpen: (id: string) => void }) {
  const live = useLiveCalls();
  const data = live.data;
  if (!data) return null;
  const busy = data.items.length > 0;
  return (
    <AnimatePresence mode="wait" initial={false}>
      {busy ? (
        <motion.section
          key="busy"
          aria-label="Live now"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          className="relative mb-5 overflow-hidden rounded-panel border border-line bg-surface shadow-1"
        >
          <span className="absolute inset-x-0 top-0 h-[2px] bg-accent" aria-hidden />
          <CardHeader count={data.count}>
            <span className="hidden text-[13px] text-fg-3 sm:inline">Open a call to follow its transcript as it happens.</span>
            <Button asChild variant="link" size="sm" className="ml-auto">
              <Link to="/calls">All calls</Link>
            </Button>
          </CardHeader>
          <LiveCallList calls={data.items} onOpen={onOpen} label="Calls on air" />
          {data.count > data.items.length && (
            <p className="border-t border-line px-5 py-2.5 text-[13px] text-fg-3">
              Showing the newest {data.items.length} of {data.count}.
            </p>
          )}
        </motion.section>
      ) : (
        <motion.section
          key="idle"
          aria-label="Live now"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="mb-5 flex items-center gap-3 rounded-panel border border-dashed border-line-strong/80 px-4 py-2.5 sm:px-5"
        >
          <span className="relative grid size-2.5 place-items-center" aria-hidden>
            <span className="size-2 rounded-full bg-line-strong" />
          </span>
          <p className="text-[13px] text-fg-3">
            <span className="font-medium text-fg-2">No calls right now.</span> Calls show here the moment they ring.
          </p>
        </motion.section>
      )}
    </AnimatePresence>
  );
}

/** Call History: calls on air pinned above the table while there are any. */
export function OnAirStrip({ onOpen }: { onOpen: (id: string) => void }) {
  const live = useLiveCalls();
  const items = live.data?.items ?? [];
  return (
    <AnimatePresence initial={false}>
      {items.length > 0 && (
        <motion.div
          key="strip"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="border-b border-line bg-[color-mix(in_srgb,var(--accent-soft)_22%,var(--surface))]"
        >
          <CardHeader count={live.data?.count ?? items.length}>
            <span className="text-[13px] text-fg-3">Pinned while they are on air</span>
          </CardHeader>
          <LiveCallList calls={items} onOpen={onOpen} label="Calls on air" />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
