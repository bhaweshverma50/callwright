import {
  BookOpenText,
  Crosshair,
  Database,
  Flask,
  ListChecks,
  PhoneCall as PhoneCallDuo,
  PhoneList,
  Robot,
  SquaresFour,
  Wallet as WalletDuo,
  WarningDiamond,
  type Icon as DuoIcon,
} from "@phosphor-icons/react";
import {
  Bot,
  BookOpen,
  Crosshair as CrosshairIcon,
  Database as DatabaseIcon,
  FlaskConical,
  LayoutDashboard,
  ListChecks as ListChecksIcon,
  PhoneCall,
  PhoneForwarded,
  Settings,
  TriangleAlert,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  /** Lucide icon for navigation and buttons. */
  icon: LucideIcon;
  /** Phosphor duotone glyph for empty states and placeholders. */
  duo: DuoIcon;
  /** Spec that ships the real page; until then the route shows a placeholder. */
  spec: string;
  /** One line for the page header: what this area is for. */
  blurb: string;
}

export interface NavGroup {
  label: string;
  /** One line on the group's place in the loop (placeholders show it). */
  role: string;
  items: NavItem[];
}

/**
 * Every product area (FR-005): 11 items in four groups that follow the life of an agent, from
 * building it to closing the feedback loop. Billing sits at the foot of the sidebar; Settings
 * sits under it in its own landmark.
 */
export const NAV: NavGroup[] = [
  {
    label: "Build",
    role: "Make the agent and give it what it needs to answer.",
    items: [
      { to: "/agents", label: "Agents", icon: Bot, duo: Robot, spec: "002", blurb: "Prompt and flow agents with their versions, voices and models." },
      { to: "/knowledge-base", label: "Knowledge", icon: BookOpen, duo: BookOpenText, spec: "005", blurb: "Documents and sites your agents can search during a call." },
      { to: "/phone-numbers", label: "Channels", icon: PhoneForwarded, duo: PhoneList, spec: "010", blurb: "Phone numbers, outbound dialling and WhatsApp voice for your agents." },
    ],
  },
  {
    label: "Observe",
    role: "Watch real calls: volume, cost, latency and outcomes.",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, duo: SquaresFour, spec: "006", blurb: "Calls, cost and quality for this workspace." },
      { to: "/calls", label: "Calls", icon: PhoneCall, duo: PhoneCallDuo, spec: "006", blurb: "Every call with its transcript, recording, per-turn latency and itemised cost." },
    ],
  },
  {
    label: "Quality",
    role: "Test changes against saved and simulated calls before callers hear them.",
    items: [
      { to: "/datasets", label: "Datasets", icon: DatabaseIcon, duo: Database, spec: "008", blurb: "Saved sets of calls to replay against a new prompt or model." },
      { to: "/simulations", label: "Simulations", icon: FlaskConical, duo: Flask, spec: "008", blurb: "Replay real callers or simulated personas against an agent version." },
    ],
  },
  {
    label: "Feedback loop",
    role: "Check the scores, then turn repeated failures into tested fixes.",
    items: [
      { to: "/review", label: "Review", icon: ListChecksIcon, duo: ListChecks, spec: "007", blurb: "A queue of calls to label, so automatic scores can be checked by people." },
      { to: "/calibration", label: "Calibration", icon: CrosshairIcon, duo: Crosshair, spec: "007", blurb: "How often each evaluator agrees with human labels, and where it drifts." },
      { to: "/issues", label: "Issues", icon: TriangleAlert, duo: WarningDiamond, spec: "009", blurb: "Repeated failures grouped into issues, each with a drafted and tested fix." },
    ],
  },
];

export const BILLING_ITEM: NavItem = {
  to: "/billing",
  label: "Billing",
  icon: Wallet,
  duo: WalletDuo,
  spec: "001",
  blurb: "Prepaid credit for calls and features, billed per second.",
};

export const SETTINGS_ITEM = { to: "/settings", label: "Settings", icon: Settings };

export const ALL_NAV_ITEMS: NavItem[] = [...NAV.flatMap((g) => g.items), BILLING_ITEM];

export function groupOf(to: string): NavGroup | undefined {
  return NAV.find((g) => g.items.some((i) => i.to === to));
}
