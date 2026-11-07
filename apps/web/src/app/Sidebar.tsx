import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { motion } from "motion/react";
import { NavLink, useMatch } from "react-router";
import { Kbd, Logo, Tooltip, TruncatedText, cn, focusRing } from "../components";
import { LiveCallsBadge } from "./LiveCallsBadge";
import { BILLING_ITEM, NAV, SETTINGS_ITEM, type NavItem } from "./nav";
import { CALLS_PATH } from "../lib/paths";

/** Rail widths (docs/DESIGN.md section 5). Shell animates between them. */
export const RAIL_EXPANDED = 248;
export const RAIL_COLLAPSED = 72;

/**
 * Labelled, grouped sidebar (FR-005, docs/DESIGN.md section 5): Build, Observe, Quality and
 * Feedback loop, then Billing, Settings and the collapse toggle at the foot. Collapsed, it is a
 * 72px rail of centred 40x40 targets with label tooltips; the active item is a contained tinted
 * square in the accent colour, expanded or collapsed. The choice is remembered per browser by Shell. In the mobile
 * drawer it is always expanded and `onNavigate` closes the drawer.
 */
export function Sidebar({
  expanded,
  onToggle,
  onNavigate,
  inDrawer = false,
}: {
  expanded: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
  inDrawer?: boolean;
}) {
  const pad = expanded ? "px-3" : "px-0";
  return (
    <div className="flex h-full min-h-0 flex-col">
      {!inDrawer && (
        <div className={cn("flex h-[60px] shrink-0 items-center", expanded ? "px-4" : "justify-center")}>
          <NavLink to="/dashboard" className={cn("rounded-[9px]", focusRing)} aria-label="Callwright dashboard">
            <Logo compact={!expanded} />
          </NavLink>
        </div>
      )}

      <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col">
        <div className={cn("flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden pb-4 pt-2", expanded ? "gap-5" : "gap-2", pad)}>
          {NAV.map((group, gi) => (
            <div key={group.label} className="flex flex-col">
              {expanded ? (
                <p className="px-2.5 pb-1.5 text-[12px] font-medium text-fg-3">{group.label}</p>
              ) : (
                gi > 0 && <div role="separator" aria-hidden className="mx-auto mb-2 h-px w-8 bg-line-strong/70" />
              )}
              <ul className={cn("flex flex-col", expanded ? "gap-0.5" : "gap-1.5")}>
                {group.items.map((item) => (
                  <li key={item.to} className="relative">
                    <SideLink item={item} expanded={expanded} group={group.label} onNavigate={onNavigate} inDrawer={inDrawer} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <ul className={cn("flex flex-col border-t border-line pt-2", expanded ? "gap-0.5" : "gap-1.5", pad)}>
          <li className="relative">
            <SideLink item={BILLING_ITEM} expanded={expanded} group={null} onNavigate={onNavigate} inDrawer={inDrawer} />
          </li>
        </ul>
      </nav>
      <nav aria-label="Workspace" className={cn("pt-0.5", expanded ? "" : "pt-1.5", pad, !onToggle && "pb-3")}>
        <ul>
          <li className="relative">
            <SideLink item={SETTINGS_ITEM} expanded={expanded} group={null} onNavigate={onNavigate} inDrawer={inDrawer} />
          </li>
        </ul>
      </nav>

      {onToggle && (
        <div className={cn("pb-3", expanded ? "pt-0.5" : "pt-1.5", pad)}>
          <Tooltip
            side="right"
            content={
              <span className="flex items-center gap-2">
                {expanded ? "Collapse" : "Expand"} navigation <Kbd>[</Kbd>
              </span>
            }
          >
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse navigation" : "Expand navigation"}
              className={cn(
                "flex cursor-pointer items-center rounded-control text-[13px] text-fg-3 transition-colors duration-150 hover:bg-surface-3 hover:text-fg",
                expanded ? "h-9 w-full gap-3 px-2.5" : "mx-auto size-10 justify-center",
                focusRing,
              )}
            >
              {expanded ? (
                <PanelLeftClose className="size-[18px] shrink-0" aria-hidden />
              ) : (
                <PanelLeftOpen className="size-[18px] shrink-0" aria-hidden />
              )}
              {expanded && <FadeLabel>Collapse</FadeLabel>}
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

function FadeLabel({ children }: { children: string }) {
  return (
    <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.18, delay: 0.06 }} className="min-w-0 flex-1 text-left">
      <TruncatedText focusable={false} side="right">
        {children}
      </TruncatedText>
    </motion.span>
  );
}

function SideLink({
  item,
  expanded,
  group,
  onNavigate,
  inDrawer,
}: {
  item: Pick<NavItem, "to" | "label" | "icon">;
  expanded: boolean;
  group: string | null;
  onNavigate?: () => void;
  inDrawer: boolean;
}) {
  const Icon = item.icon;
  // Computed here rather than through NavLink's className function: Tooltip's Slot merges
  // class names as strings, which would drop a function.
  const active = Boolean(useMatch({ path: item.to, end: false }));
  return (
    <>
      <Tooltip content={group ? `${group}: ${item.label}` : item.label} side="right" enabled={!expanded}>
        <NavLink
          to={item.to}
          onClick={onNavigate}
          aria-label={expanded ? undefined : item.label}
          className={cn(
            "group relative flex items-center rounded-control text-[14px] transition-[background-color,color,box-shadow] duration-150",
            expanded ? cn("w-full gap-3 px-2.5", inDrawer ? "h-11" : "h-9") : "mx-auto size-10 justify-center",
            // Active: a contained tinted square, icon and label in the accent colour. No side bars.
            active ? "bg-accent-soft font-medium text-accent-text" : "text-fg-2 hover:bg-surface-3/80 hover:text-fg",
            focusRing,
          )}
        >
          <Icon
            className={cn("size-[18px] shrink-0 transition-colors", active ? "text-accent-text" : "text-fg-3 group-hover:text-fg-2")}
            strokeWidth={1.75}
            aria-hidden
          />
          {expanded && <FadeLabel>{item.label}</FadeLabel>}
          {item.to === CALLS_PATH && <LiveCallsBadge expanded={expanded} />}
        </NavLink>
      </Tooltip>
    </>
  );
}
