import { Calculator, Clock3, Eye, Hammer, RefreshCcw, ShieldCheck, Wallet } from "lucide-react";
import { Link, useParams } from "react-router";
import { ALL_NAV_ITEMS, groupOf, type NavItem } from "../../app/nav";
import { Badge, Button, ChainStrip, PageHeader, type ChainNode } from "../../components";
import { RecordNotFound } from "../NotFound";

const ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

const LOOP: ChainNode[] = [
  { key: "Build", label: "Build", icon: <Hammer aria-hidden /> },
  { key: "Observe", label: "Observe", icon: <Eye aria-hidden /> },
  { key: "Quality", label: "Quality", icon: <ShieldCheck aria-hidden /> },
  { key: "Feedback loop", label: "Feedback loop", icon: <RefreshCcw aria-hidden /> },
];

/**
 * Placeholder for areas whose spec has not shipped yet (T043). It names what the area will hold,
 * shows where it sits in the build, observe, test and fix loop, and points at what works today.
 */
export function AreaPlaceholder({ to }: { to: string }) {
  const item = ALL_NAV_ITEMS.find((n) => n.to === to) as NavItem;
  const group = groupOf(to);
  const Duo = item.duo;
  return (
    <>
      <PageHeader title={item.label} description={item.blurb} actions={<Badge icon={<Clock3 />}>In a later release</Badge>} />
      <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
        <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-60" />
        <div className="relative grid gap-10 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
          <div className="flex flex-col items-start gap-4">
            <span className="grid size-14 place-items-center rounded-panel border border-accent/20 bg-accent-soft text-accent-text">
              <Duo weight="duotone" className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-[19px] font-medium tracking-[-0.015em] text-fg">{item.label} is being built</h2>
            <p className="max-w-[52ch] text-[14px] leading-relaxed text-fg-2">
              Your account, credit and pricing already work, so anything you set up here later is billed from the same balance at the same per-minute
              rates.
            </p>
            <div className="mt-1 flex flex-wrap gap-2">
              <Button asChild variant="secondary" icon={<Wallet aria-hidden />}>
                <Link to="/billing">Check balance and usage</Link>
              </Button>
              <Button asChild variant="ghost" icon={<Calculator aria-hidden />}>
                <Link to="/pricing">See per-minute pricing</Link>
              </Button>
            </div>
          </div>
          {group && (
            <div className="rounded-panel border border-line bg-surface-2/70 px-5 py-6">
              <p className="text-[13px] font-medium text-fg">Where {item.label.toLowerCase()} fits</p>
              <ChainStrip nodes={LOOP} active={group.label} flow className="mt-5" />
              <p className="mt-5 text-[13.5px] leading-relaxed text-fg-2">
                <span className="font-medium text-fg">{group.label}:</span> {group.role}
              </p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

/**
 * Record addresses for areas not shipped yet (`/agents/:id`, `/issues/:id`). A malformed id shows
 * the plain not-found view naming the record kind (US1.7); a well-formed one shows the area
 * placeholder.
 */
export function RecordPlaceholder({ to, prefix, kind }: { to: string; prefix: string; kind: string }) {
  const { id = "" } = useParams();
  const [p, rest] = [id.slice(0, prefix.length + 1), id.slice(prefix.length + 1)];
  const item = ALL_NAV_ITEMS.find((n) => n.to === to) as NavItem;
  if (p !== `${prefix}_` || !ULID.test(rest)) return <RecordNotFound kind={kind} backTo={to} backLabel={`Back to ${item.label}`} />;
  return <AreaPlaceholder to={to} />;
}
