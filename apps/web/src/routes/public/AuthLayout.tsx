import type { ReactNode } from "react";
import { Link } from "react-router";
import { LatencyChip, Logo, Reveal, RevealItem, Waveform, cn, focusRing } from "../../components";
import { formatUsd } from "../../lib/money";
import { SAMPLE_CALL, SAMPLE_CALL_SECONDS } from "../../lib/sampleCall";
import { SEED_PER_MINUTE_MICROS } from "../../lib/stack";

const TURNS = SAMPLE_CALL.slice(0, 3);
const COST = formatUsd((SEED_PER_MINUTE_MICROS * BigInt(SAMPLE_CALL_SECONDS)) / 60n, { places: 4 });

/**
 * Split layout for sign-in, register and password pages (docs/DESIGN.md section 6): the form on
 * one side and, on wide screens, a quiet sample call on the other: a slow waveform, three turns
 * with their latency, and what the call cost.
 */
export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-dvh grid-cols-[minmax(0,1fr)] bg-bg lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="flex flex-col px-5 py-6 sm:px-12">
        <Link to="/" className={cn("self-start rounded-[9px]", focusRing)} aria-label="Callwright home">
          <Logo />
        </Link>
        <main id="main" className="flex flex-1 items-center py-12">
          <Reveal className="w-full max-w-[400px]">
            <RevealItem>
              <h1 className="font-display text-[26px] font-semibold leading-[1.12] tracking-[-0.03em] text-fg sm:text-[30px]">{title}</h1>
            </RevealItem>
            {subtitle && (
              <RevealItem>
                <p className="mt-3 text-[14.5px] leading-relaxed text-fg-2">{subtitle}</p>
              </RevealItem>
            )}
            <RevealItem className="mt-8">{children}</RevealItem>
            {footer && <RevealItem className="mt-7 text-[14px] text-fg-2">{footer}</RevealItem>}
          </Reveal>
        </main>
        <p className="flex gap-5 text-[12.5px] text-fg-3">
          <Link to="/privacy" className={cn("link-underline hover:text-fg", focusRing)}>
            Privacy
          </Link>
          <Link to="/terms" className={cn("link-underline hover:text-fg", focusRing)}>
            Terms
          </Link>
        </p>
      </div>
      <aside
        aria-label="A sample call"
        className="relative hidden overflow-hidden bg-console text-console-fg lg:flex lg:items-center lg:justify-center"
      >
        <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0" />
        <div className="relative w-full max-w-[500px] px-10 py-12">
          <p className="max-w-[24ch] font-display text-[22px] font-medium leading-[1.25] tracking-[-0.02em]">
            Every turn timed. Every second priced.
          </p>
          <div className="mt-8 rounded-feature border border-console-line bg-console-2/70 p-5 backdrop-blur-sm">
            <div className="flex items-center justify-between text-[12px] text-console-fg-2">
              <span>Sample call, front desk agent</span>
              <span>
                <span className="font-mono text-console-fg tnum">0:{SAMPLE_CALL_SECONDS}</span>
              </span>
            </div>
            <Waveform bars={56} seed={11} progress={0.72} live onConsole height={40} className="mt-4 [&_rect]:[animation-duration:2.4s!important]" />
            <ol className="mt-5 flex flex-col gap-3">
              {TURNS.map((t, i) => (
                <li key={i} className={cn("flex flex-col gap-1.5", t.who === "agent" ? "items-end text-right" : "items-start")}>
                  <span className="text-[11.5px] font-medium text-console-fg-2">{t.who === "agent" ? "Agent" : "Caller"}</span>
                  <p
                    className={cn(
                      "max-w-[32ch] rounded-panel px-3.5 py-2 text-[13px] leading-snug",
                      t.who === "agent" ? "rounded-br-[4px] bg-[#2a33a8] text-white" : "rounded-bl-[4px] bg-console text-console-fg",
                    )}
                  >
                    {t.text}
                  </p>
                  {t.latency && <LatencyChip latency={t.latency} onConsole />}
                </li>
              ))}
            </ol>
            <div className="mt-5 flex items-center justify-between border-t border-console-line pt-4 text-[12.5px] text-console-fg-2">
              <span>Whole call</span>
              <span className="font-mono text-[14px] text-console-fg tnum">{COST}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
