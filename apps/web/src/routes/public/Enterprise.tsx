import { ArrowUpRight } from "@phosphor-icons/react";
import { Button } from "../../components";
import { env } from "../../lib/env";

const OFFERS = [
  { title: "Volume rates", text: "Lower per-minute pricing for committed monthly minutes, invoiced instead of prepaid." },
  { title: "Higher concurrency", text: "Run more calls at once than the default limit of five per workspace." },
  { title: "Your own telephony", text: "Bring SIP trunks and numbers you already own, inbound and outbound." },
  { title: "Retention and residency", text: "Recording and transcript retention set to your policy, with encrypted storage." },
];

/** Enterprise contact (T044, FR-016). The contact link comes from VITE_SALES_CONTACT_URL. */
export function Enterprise() {
  return (
    <div className="mx-auto grid max-w-[1200px] gap-14 px-4 pb-24 pt-14 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div>
        <h1 className="max-w-[18ch] font-display text-[40px] font-semibold leading-[1.05] tracking-[-0.03em] text-fg">Running voice at scale?</h1>
        <p className="mt-4 max-w-[48ch] text-[15px] leading-relaxed text-fg-2">
          Tell us your call volume, channels and compliance needs. We reply within one business day with a plan and a price.
        </p>
        <Button asChild variant="primary" size="lg" className="mt-8">
          <a href={env.salesContactUrl}>
            Contact sales <ArrowUpRight aria-hidden />
          </a>
        </Button>
      </div>
      <dl className="grid gap-px self-start overflow-hidden rounded-panel border border-line bg-line sm:grid-cols-2">
        {OFFERS.map((o) => (
          <div key={o.title} className="flex flex-col gap-1.5 bg-surface p-6">
            <dt className="text-[14px] font-medium text-fg">{o.title}</dt>
            <dd className="text-[13.5px] leading-relaxed text-fg-2">{o.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
