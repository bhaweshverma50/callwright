import { ChevronLeft, ChevronRight, PhoneIncoming, PhoneOutgoing } from "lucide-react";
import { useRef } from "react";
import { Button, IconButton } from "../../../components";
import { SCENARIOS } from "../playground/scenarios";

/** The seed templates (services/api/app/templates/seed), in the order the gallery lists them. */
const TEMPLATES = [
  {
    id: "05-healthcare-triage-booking",
    industry: "Healthcare",
    name: "Symptom triage and booking",
    inbound: true,
    text: "Screens for emergencies first, recommends a department and books a visit.",
  },
  {
    id: "06-automotive-roadside-ev",
    industry: "Automotive",
    name: "Roadside and EV assistance",
    inbound: true,
    text: "Checks the caller is safe, then dispatches a tow or a mobile charge with an arrival time.",
  },
  {
    id: "01-banking-collections",
    industry: "Banking",
    name: "Loan payment reminder",
    inbound: false,
    text: "Calls about an overdue instalment and ends with a payment or a promise-to-pay date.",
  },
  {
    id: "08-banking-customer-line",
    industry: "Banking",
    name: "Bank customer line",
    inbound: true,
    text: "Recorded-line disclosure up front, then card, payment and balance questions.",
  },
  {
    id: "09-collections-return-call",
    industry: "Collections",
    name: "Collections return call",
    inbound: true,
    text: "Verifies the right party, gives the debt-collection disclosure and agrees a payment.",
  },
  {
    id: "02-banking-loan-telesales",
    industry: "Banking",
    name: "Personal loan offer",
    inbound: false,
    text: "Presents a pre-approved loan and completes the application with consent.",
  },
  {
    id: "03-telecom-plan-upgrade",
    industry: "Telecom",
    name: "Mobile plan upgrade",
    inbound: false,
    text: "Moves prepaid customers to a postpaid or family 5G plan and confirms the switch.",
  },
  {
    id: "04-ecommerce-credit-offer",
    industry: "Retail",
    name: "Shopping credit and membership",
    inbound: false,
    text: "Offers a pay-later credit line and walks the customer through activation.",
  },
  {
    id: "07-healthcare-previsit-checkin",
    industry: "Healthcare",
    name: "Pre-visit patient check-in",
    inbound: false,
    text: "Confirms details before an appointment and explains how to prepare.",
  },
];

/** Asks the home playground to switch to a scenario and scrolls up to it. */
function tryInPlayground(scenarioKey: string) {
  window.dispatchEvent(new CustomEvent("cw:playground", { detail: scenarioKey }));
  document.getElementById("playground")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** Horizontal rail of the industry templates; the ones with a demo agent can be called right away. */
export function TemplateRail() {
  const rail = useRef<HTMLUListElement>(null);
  const page = (dir: 1 | -1) => rail.current?.scrollBy({ left: dir * rail.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <div>
      <div className="mx-auto flex max-w-[1200px] items-end justify-between gap-6 px-4 sm:px-6">
        <div>
          <h2 id="templates" className="max-w-[20ch] font-display text-[26px] leading-[1.15] tracking-[-0.025em] text-fg sm:text-[32px]">
            Start from an agent that already works.
          </h2>
          <p className="mt-4 max-w-[52ch] text-[15px] leading-relaxed text-fg-2">
            Nine templates written for real call centre work, with the disclosures each industry needs. Copy one, change the details, put it on a
            number.
          </p>
        </div>
        <div className="hidden shrink-0 gap-2 md:flex">
          <IconButton label="Previous templates" onClick={() => page(-1)} className="border border-line">
            <ChevronLeft aria-hidden />
          </IconButton>
          <IconButton label="Next templates" onClick={() => page(1)} className="border border-line">
            <ChevronRight aria-hidden />
          </IconButton>
        </div>
      </div>
      <ul
        ref={rail}
        aria-labelledby="templates"
        className="mt-10 flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-px-4 px-4 pb-4 [scrollbar-width:none] sm:scroll-px-6 sm:px-6 xl:scroll-px-[calc((100vw-1200px)/2+24px)] xl:px-[calc((100vw-1200px)/2+24px)] [&::-webkit-scrollbar]:hidden"
      >
        {TEMPLATES.map((t) => {
          const demo = SCENARIOS.find((s) => s.template === t.id);
          const Dir = t.inbound ? PhoneIncoming : PhoneOutgoing;
          return (
            <li
              key={t.id}
              className="flex w-[290px] shrink-0 snap-start flex-col rounded-feature border border-line bg-surface p-6 shadow-1 sm:w-[320px]"
            >
              <p className="flex items-center justify-between gap-3 text-[13px] text-fg-3">
                <span>{t.industry}</span>
                <span className="flex items-center gap-1.5">
                  <Dir className="size-3.5" aria-hidden />
                  {t.inbound ? "Answers calls" : "Places calls"}
                </span>
              </p>
              <h3 className="mt-6 text-[18px] font-semibold leading-snug text-fg">{t.name}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-fg-2">{t.text}</p>
              <div className="mt-auto pt-6">
                {demo ? (
                  <Button variant="secondary" size="sm" onClick={() => tryInPlayground(demo.key)}>
                    Try it now
                  </Button>
                ) : (
                  <span className="text-[13px] text-fg-3">In the template gallery</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
