import { CircleCheck, CircleX, LoaderCircle } from "lucide-react";
import { motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { LatencyChip, OnAir, Ticker, cn } from "../../../components";

const EASE = [0.16, 1, 0.3, 1] as const;

const STEPS = [
  {
    title: "See every call",
    text: "Transcript, recording, per-turn latency and the itemised cost of each call, as it happens.",
    Scene: CallsScene,
  },
  {
    title: "Score it, then check the score",
    text: "Evaluators grade calls with their reasons. Your own labels show how often each one agrees with a person.",
    Scene: VerdictScene,
  },
  {
    title: "Fix what repeats",
    text: "Repeated failures become issues with a drafted prompt fix, replayed against the calls it would change before you apply it.",
    Scene: FixScene,
  },
];

/**
 * The quality loop as a scroll story: on wide screens the steps scroll past a sticky panel that
 * swaps to the step in view; on narrow screens each step carries its own panel.
 */
export function QualityStory() {
  const [active, setActive] = useState(0);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-x-16 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <ol>
        {STEPS.map((s, i) => (
          <StoryStep key={s.title} index={i} onEnter={setActive} active={i === active}>
            <h3 className="font-display text-[22px] font-medium leading-[1.2] tracking-[-0.02em] text-fg sm:text-[26px]">{s.title}</h3>
            <p className="mt-3 max-w-[42ch] text-[15.5px] leading-relaxed text-fg-2">{s.text}</p>
            <div className="mt-8 lg:hidden">
              <Frame>
                <s.Scene />
              </Frame>
            </div>
          </StoryStep>
        ))}
      </ol>
      <div className="hidden lg:block">
        <div className="sticky top-[calc(50vh-190px)]">
          {/* Every scene sits in the same grid cell, so the frame keeps the tallest one's height and a
              swap is a crossfade with nothing mounting or unmounting. */}
          <Frame className="grid [&>*]:[grid-area:1/1]">
            {STEPS.map((st, i) => (
              <div
                key={st.title}
                aria-hidden={i !== active}
                className={cn("transition-opacity duration-300 ease-out", i === active ? "opacity-100" : "pointer-events-none opacity-0")}
              >
                <st.Scene active={i === active} />
              </div>
            ))}
          </Frame>
        </div>
      </div>
    </div>
  );
}

function StoryStep({ index, active, onEnter, children }: { index: number; active: boolean; onEnter: (i: number) => void; children: ReactNode }) {
  const ref = useRef<HTMLLIElement>(null);
  const inView = useInView(ref, { margin: "-50% 0px -50% 0px" });
  useEffect(() => {
    if (inView) onEnter(index);
  }, [inView, index, onEnter]);
  return (
    <li
      ref={ref}
      className={cn(
        "border-t border-line py-10 transition-opacity duration-300 first:border-t-0 lg:flex lg:min-h-[52vh] lg:flex-col lg:justify-center lg:border-t-0 lg:py-0",
        !active && "lg:opacity-40",
      )}
    >
      {children}
    </li>
  );
}

function Frame({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("min-h-[380px] rounded-feature border border-line bg-surface p-5 shadow-2 sm:p-6", className)}>{children}</div>;
}

const usd = (n: number) => `$${n.toFixed(4)}`;

function CallsScene(_: { active?: boolean }) {
  const reduce = useReducedMotion();
  const [cost, setCost] = useState(0.0412);
  useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setCost((c) => c + 0.0018), 1000);
    return () => clearInterval(t);
  }, [reduce]);
  const rows = [
    { who: "+44 7700 900123", agent: "Front desk", len: "4:12", cost: "$0.4410", latency: { stt: 170, llm: 450, tts: 200 } },
    { who: "+44 7700 900456", agent: "Front desk", len: "1:48", cost: "$0.1890", latency: { stt: 210, llm: 520, tts: 180 } },
    { who: "+44 7700 900789", agent: "Roadside", len: "6:03", cost: "$0.6342", latency: { stt: 190, llm: 610, tts: 230 } },
  ];
  return (
    <div className="flex flex-col">
      <p className="text-[13px] font-medium text-fg-2">Calls</p>
      <div className="mt-3 flex items-center justify-between gap-4 rounded-panel bg-surface-2 px-4 py-3.5">
        <div className="min-w-0">
          <OnAir label="Live, front desk" />
          <p className="mt-1 truncate text-[13.5px] text-fg-2">&ldquo;Can I come in tomorrow morning?&rdquo;</p>
        </div>
        <Ticker value={cost} format={usd} className="font-mono text-[18px] text-fg" />
      </div>
      <ul className="mt-2 divide-y divide-line">
        {rows.map((r) => (
          <li key={r.who} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 px-1 py-3 text-[13.5px]">
            <span className="min-w-0">
              <span className="block truncate font-mono text-fg">{r.who}</span>
              <span className="text-fg-3">
                {r.agent}, {r.len}
              </span>
            </span>
            <LatencyChip latency={r.latency} className="max-sm:hidden" />
            <span className="font-mono text-fg tnum">{r.cost}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VerdictScene({ active = true }: { active?: boolean }) {
  const reduce = useReducedMotion();
  const [done, setDone] = useState(!!reduce);
  // The verdict lands each time the scene comes into view.
  useEffect(() => {
    if (reduce) return;
    if (!active) {
      setDone(false);
      return;
    }
    const t = setTimeout(() => setDone(true), 1400);
    return () => clearTimeout(t);
  }, [reduce, active]);
  const checks = [
    { name: "Screened for emergencies first", pass: true },
    { name: "Confirmed the patient's date of birth", pass: false, pending: true },
    { name: "Booked a time the caller agreed to", pass: true },
  ];
  return (
    <div className="flex flex-col">
      <p className="text-[13px] font-medium text-fg-2">Quality checks, call from 10:42</p>
      <ul className="mt-3 flex flex-col gap-2">
        {checks.map((c) => {
          const waiting = c.pending && !done;
          return (
            <li key={c.name} className="rounded-panel border border-line px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[14px] text-fg">{c.name}</span>
                {waiting ? (
                  <span className="flex items-center gap-1.5 text-[13px] text-fg-3">
                    <LoaderCircle className="size-4 animate-spin" aria-hidden />
                    Checking
                  </span>
                ) : c.pass ? (
                  <span className="flex items-center gap-1.5 text-[13px] font-medium text-success-text">
                    <CircleCheck className="size-4" aria-hidden />
                    Pass
                  </span>
                ) : (
                  <motion.span
                    initial={reduce ? false : { opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="flex items-center gap-1.5 text-[13px] font-medium text-danger-text"
                  >
                    <CircleX className="size-4" aria-hidden />
                    Fail
                  </motion.span>
                )}
              </div>
              {c.pending && done && (
                <motion.p
                  initial={reduce ? false : { opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  transition={{ duration: 0.3, ease: EASE }}
                  className="overflow-hidden text-[13px] leading-relaxed text-fg-2"
                >
                  <span className="block pt-2">
                    The agent booked the visit before asking for a date of birth, so the record could not be matched.
                  </span>
                </motion.p>
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-5 text-[13.5px] text-fg-2">
        This check agrees with your reviewers on <span className="font-mono text-fg tnum">92%</span> of labelled calls.
      </p>
    </div>
  );
}

function FixScene({ active = true }: { active?: boolean }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex flex-col">
      <p className="text-[13px] font-medium text-fg-2">Issue seen in 14 calls this week</p>
      <p className="mt-2 text-[16px] font-semibold text-fg">Books a visit without the patient&apos;s date of birth</p>
      <div className="mt-4 overflow-hidden rounded-panel border border-line font-mono text-[12.5px] leading-relaxed">
        <p className="bg-danger-soft px-3 py-1.5 text-danger-text">- Book the earliest slot the caller accepts.</p>
        <p className="bg-success-soft px-3 py-1.5 text-success-text">+ Ask for the date of birth and confirm it before booking any slot.</p>
      </div>
      <div className="mt-5">
        <div className="flex items-baseline justify-between text-[13.5px]">
          <span className="text-fg-2">Replayed on the 14 calls</span>
          <span className="font-mono text-fg tnum">13 now ask first</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
          <motion.div
            className="h-full rounded-full bg-[linear-gradient(90deg,var(--heat-1),var(--heat-2),var(--heat-3))]"
            initial={reduce ? false : { width: "0%" }}
            animate={{ width: active || reduce ? `${(13 / 14) * 100}%` : "0%" }}
            transition={{ duration: 1.4, ease: EASE, delay: 0.3 }}
          />
        </div>
      </div>
      <p className="mt-5 text-[13.5px] text-fg-3">Nothing changes until you apply the fix.</p>
    </div>
  );
}
