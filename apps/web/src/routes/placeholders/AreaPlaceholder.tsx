import { ArrowRight } from "@phosphor-icons/react";
import { Link, useParams } from "react-router";
import { ALL_NAV_ITEMS, type NavItem } from "../../app/nav";
import { Badge, Button, EmptyState, PageHeader } from "../../components";
import { RecordNotFound } from "../NotFound";

const ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

/**
 * Placeholder for areas whose spec has not shipped yet (T043). It names what the area will hold
 * so the navigation is honest, and points at what works today.
 */
export function AreaPlaceholder({ to }: { to: string }) {
  const item = ALL_NAV_ITEMS.find((n) => n.to === to) as NavItem;
  const Icon = item.icon;
  return (
    <>
      <PageHeader title={item.label} description={item.blurb} actions={<Badge>Not available yet</Badge>} />
      <div className="rounded-panel border border-dashed border-line-strong bg-surface/60 px-6">
        <EmptyState
          icon={<Icon />}
          title={`${item.label} arrives in a later release`}
          actions={
            <>
              <Button asChild variant="secondary">
                <Link to="/billing">
                  Check balance and usage <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild variant="ghost">
                <Link to="/pricing">See per-minute pricing</Link>
              </Button>
            </>
          }
        >
          <p>
            This part of the workspace is being built. Your account, credit and pricing already work, so anything you set up
            here later is billed from the same balance.
          </p>
        </EmptyState>
      </div>
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
