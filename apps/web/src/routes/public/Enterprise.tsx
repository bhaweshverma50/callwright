import { Gauge, Mail, PhoneIncoming, ShieldCheck, TrendingDown } from "lucide-react";
import { Button } from "../../components";
import { env } from "../../lib/env";

const OFFERS = [
  { icon: TrendingDown, title: "Volume rates", text: "Lower per-minute pricing for committed monthly minutes, invoiced instead of prepaid." },
  { icon: Gauge, title: "Higher concurrency", text: "Run more calls at once than the default limit of five per workspace." },
  { icon: PhoneIncoming, title: "Your own telephony", text: "Bring SIP trunks and numbers you already own, inbound and outbound." },
  { icon: ShieldCheck, title: "Retention and residency", text: "Recording and transcript retention set to your policy, with encrypted storage." },
];

/** Enterprise contact (T044, FR-016). The contact link comes from VITE_SALES_CONTACT_URL. */
export function Enterprise() {
  return (
    <div className="mx-auto grid max-w-[1200px] grid-cols-[minmax(0,1fr)] gap-14 px-4 pb-24 pt-12 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:pt-16">
      <div>
        <h1 className="max-w-[16ch] font-display text-[32px] font-semibold leading-[1.08] tracking-[-0.03em] text-fg sm:text-[42px]">
          Running voice at scale?
        </h1>
        <p className="mt-5 max-w-[46ch] text-[16px] leading-relaxed text-fg-2">
          Tell us your call volume, channels and compliance needs. We reply within one business day with a plan and a price.
        </p>
        <Button asChild variant="primary" size="lg" className="mt-8" icon={<Mail aria-hidden />}>
          <a href={env.salesContactUrl}>Contact sales</a>
        </Button>
      </div>
      <dl className="grid gap-4 self-start sm:grid-cols-2">
        {OFFERS.map((o) => (
          <div key={o.title} className="lift flex flex-col gap-2 rounded-panel border border-line bg-surface p-6 shadow-1">
            <o.icon className="size-5 text-accent-text" aria-hidden />
            <dt className="mt-2 text-[15px] font-semibold text-fg">{o.title}</dt>
            <dd className="text-[14px] leading-relaxed text-fg-2">{o.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
