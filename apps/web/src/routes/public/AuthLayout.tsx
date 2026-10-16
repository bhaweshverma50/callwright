import type { ReactNode } from "react";
import { Link } from "react-router";
import { CostBreakdownCard, Logo, focusRing, cn } from "../../components";
import { referenceBreakdown } from "./reference";

/**
 * Split layout for sign-in, register and password pages: the form on the left, and on wide
 * screens a live component on the right (the reference call's real cost breakdown), so the
 * first thing an operator sees is how Callwright bills.
 */
export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-bg lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="flex flex-col px-6 py-6 sm:px-12">
        <Link to="/" className={cn("self-start rounded-[7px]", focusRing)} aria-label="Callwright home">
          <Logo />
        </Link>
        <main className="flex flex-1 items-center py-12">
          <div className="w-full max-w-[380px]">
            <h1 className="font-display text-[28px] font-semibold leading-[1.1] tracking-[-0.025em] text-fg">{title}</h1>
            {subtitle && <p className="mt-2 text-[13.5px] leading-relaxed text-fg-2">{subtitle}</p>}
            <div className="mt-7">{children}</div>
            {footer && <div className="mt-6 text-[13px] text-fg-2">{footer}</div>}
          </div>
        </main>
        <p className="font-mono text-[11px] text-fg-3">
          <Link to="/privacy" className="hover:text-fg">
            Privacy
          </Link>
          <span className="mx-2">/</span>
          <Link to="/terms" className="hover:text-fg">
            Terms
          </Link>
        </p>
      </div>
      <aside aria-label="How a call is billed" className="relative hidden overflow-hidden border-l border-line bg-surface-2 lg:flex lg:items-center lg:justify-center">
        <div aria-hidden className="pointer-events-none absolute inset-0 [background-image:radial-gradient(var(--border)_1px,transparent_1px)] [background-size:18px_18px] opacity-70" />
        <div className="relative w-full max-w-[520px] px-10">
          <p className="mb-5 max-w-[34ch] font-display text-[22px] font-medium leading-[1.2] tracking-[-0.02em] text-fg">
            Every second of every call, priced line by line.
          </p>
          <CostBreakdownCard breakdown={referenceBreakdown} title="Support call, 4 min 31 s" className="shadow-pop" />
          <p className="mt-4 text-[12.5px] leading-relaxed text-fg-3">
            Long prompts cost more only when they pass the per-minute bundle. The surcharge is shown, never hidden.
          </p>
        </div>
      </aside>
    </div>
  );
}
