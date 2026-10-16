import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { motion } from "motion/react";
import { NavLink } from "react-router";
import { Kbd, Logo, Tooltip, cn, focusRing } from "../components";
import { BILLING_ITEM, NAV, SETTINGS_ITEM, type NavItem } from "./nav";

/**
 * Labelled, grouped sidebar (FR-005, docs/DESIGN.md section 5): Build, Observe, Quality and
 * Feedback loop, then Billing and Settings at the foot. Collapses to an icon rail with label
 * tooltips; the choice is remembered per browser by Shell. In the mobile drawer it is always
 * expanded and `onNavigate` closes the drawer.
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
  const markerId = inDrawer ? "nav-marker-drawer" : "nav-marker";
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
        <div className={cn("flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto overflow-x-hidden pb-4 pt-2", expanded ? "px-3" : "px-2.5")}>
          {NAV.map((group, gi) => (
            <div key={group.label} className="flex flex-col gap-0.5">
              {expanded ? (
                <p className="px-2.5 pb-1.5 text-[12px] font-medium text-fg-3">{group.label}</p>
              ) : (
                gi > 0 && <div role="separator" className="mx-2 mb-2 h-px bg-line" />
              )}
              <ul className="flex flex-col gap-0.5">
                {group.items.map((item) => (
                  <li key={item.to}>
                    <SideLink item={item} expanded={expanded} group={group.label} markerId={markerId} onNavigate={onNavigate} inDrawer={inDrawer} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className={cn("border-t border-line pt-2", expanded ? "px-3" : "px-2.5")}>
          <SideLink item={BILLING_ITEM} expanded={expanded} group={null} markerId={markerId} onNavigate={onNavigate} inDrawer={inDrawer} />
        </div>
      </nav>
      <nav aria-label="Workspace" className={cn("pb-2", expanded ? "px-3" : "px-2.5")}>
        <SideLink item={SETTINGS_ITEM} expanded={expanded} group={null} markerId={markerId} onNavigate={onNavigate} inDrawer={inDrawer} />
      </nav>

      {onToggle && (
        <div className={cn("border-t border-line py-2", expanded ? "px-3" : "px-2.5")}>
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
                "flex h-9 w-full cursor-pointer items-center gap-3 rounded-control px-2.5 text-[13px] text-fg-3 transition-colors hover:bg-surface-3 hover:text-fg",
                !expanded && "justify-center px-0",
                focusRing,
              )}
            >
              {expanded ? (
                <PanelLeftClose className="size-[18px] shrink-0" aria-hidden />
              ) : (
                <PanelLeftOpen className="size-[18px] shrink-0" aria-hidden />
              )}
              {expanded && <span>Collapse</span>}
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

function SideLink({
  item,
  expanded,
  group,
  markerId,
  onNavigate,
  inDrawer,
}: {
  item: Pick<NavItem, "to" | "label" | "icon">;
  expanded: boolean;
  group: string | null;
  markerId: string;
  onNavigate?: () => void;
  inDrawer: boolean;
}) {
  const Icon = item.icon;
  return (
    <Tooltip content={group ? `${group}: ${item.label}` : item.label} side="right" enabled={!expanded}>
      <NavLink
        to={item.to}
        onClick={onNavigate}
        aria-label={expanded ? undefined : item.label}
        className={({ isActive }) =>
          cn(
            "group relative flex items-center gap-3 rounded-control px-2.5 text-[13.5px] transition-colors duration-150",
            inDrawer ? "h-11" : "h-9",
            !expanded && "justify-center px-0",
            isActive ? "font-medium text-fg" : "text-fg-2 hover:bg-surface-3/70 hover:text-fg",
            focusRing,
          )
        }
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <motion.span
                layoutId={markerId}
                aria-hidden
                className="absolute inset-0 rounded-control border border-line bg-surface shadow-1"
                transition={{ type: "spring", stiffness: 520, damping: 42 }}
              >
                <span className="grad-action absolute inset-y-2 left-0 w-[3px] rounded-r-full" />
              </motion.span>
            )}
            <Icon
              className={cn("relative size-[18px] shrink-0 transition-colors", isActive ? "text-accent-text" : "text-fg-3 group-hover:text-fg-2")}
              strokeWidth={1.75}
              aria-hidden
            />
            {expanded && <span className="relative truncate">{item.label}</span>}
          </>
        )}
      </NavLink>
    </Tooltip>
  );
}
