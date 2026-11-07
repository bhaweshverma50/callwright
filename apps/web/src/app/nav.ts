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
import { AGENTS_PATH, BILLING_PATH, CALLS_PATH, DASHBOARD_PATH, SETTINGS_PATH } from "../lib/paths";

export interface NavItem {
  to: string;
  label: string;
  /** Lucide icon for navigation and buttons. */
  icon: LucideIcon;
}

export interface NavGroup {
  label: string;
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
    items: [
      { to: AGENTS_PATH, label: "Agents", icon: Bot },
      {
        to: "/knowledge-base",
        label: "Knowledge",
        icon: BookOpen,
      },
      {
        to: "/phone-numbers",
        label: "Channels",
        icon: PhoneForwarded,
      },
    ],
  },
  {
    label: "Observe",
    items: [
      {
        to: DASHBOARD_PATH,
        label: "Dashboard",
        icon: LayoutDashboard,
      },
      {
        to: CALLS_PATH,
        label: "Calls",
        icon: PhoneCall,
      },
    ],
  },
  {
    label: "Quality",
    items: [
      {
        to: "/datasets",
        label: "Datasets",
        icon: DatabaseIcon,
      },
      {
        to: "/simulations",
        label: "Simulations",
        icon: FlaskConical,
      },
    ],
  },
  {
    label: "Feedback loop",
    items: [
      {
        to: "/review",
        label: "Review",
        icon: ListChecksIcon,
      },
      {
        to: "/calibration",
        label: "Calibration",
        icon: CrosshairIcon,
      },
      {
        to: "/issues",
        label: "Issues",
        icon: TriangleAlert,
      },
    ],
  },
];

export const BILLING_ITEM: NavItem = {
  to: BILLING_PATH,
  label: "Billing",
  icon: Wallet,
};

export const SETTINGS_ITEM: NavItem = { to: SETTINGS_PATH, label: "Settings", icon: Settings };
