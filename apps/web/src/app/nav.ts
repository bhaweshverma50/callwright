import {
  BookOpenText,
  Crosshair,
  CreditCard,
  Database,
  Flask,
  ListChecks,
  PhoneCall,
  PhoneList,
  Robot,
  SquaresFour,
  WarningDiamond,
  type Icon,
} from "@phosphor-icons/react";

export interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  /** Spec that ships the real page; until then the route shows a placeholder. */
  spec: string;
  /** One line for the placeholder empty state: what this area will hold. */
  blurb: string;
}

export interface NavGroup {
  /** Section header in the expanded rail; null for the ungrouped top block. */
  label: string | null;
  items: NavItem[];
}

/**
 * Every product area (FR-005, US1.10): 11 items. "Quality" groups Datasets and Simulations,
 * "Feedback" groups Review, Calibration and Issues. Billing sits at the bottom of the rail.
 */
export const NAV: NavGroup[] = [
  {
    label: "Build",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: SquaresFour, spec: "006", blurb: "Call volume, cost, latency and quality for the period you pick." },
      { to: "/agents", label: "Agents", icon: Robot, spec: "002", blurb: "Prompt and flow agents, their versions, voices and models." },
      { to: "/calls", label: "Calls", icon: PhoneCall, spec: "006", blurb: "Every call with transcript, recording, per-turn latency and itemised cost." },
      { to: "/phone-numbers", label: "Channels", icon: PhoneList, spec: "010", blurb: "SIP numbers, outbound dialing and WhatsApp voice channels attached to agents." },
      { to: "/knowledge-base", label: "Knowledge", icon: BookOpenText, spec: "005", blurb: "Documents and sites your agents can search during a call." },
    ],
  },
  {
    label: "Quality",
    items: [
      { to: "/datasets", label: "Datasets", icon: Database, spec: "008", blurb: "Saved sets of calls to replay against a new prompt or model." },
      { to: "/simulations", label: "Simulations", icon: Flask, spec: "008", blurb: "Replay real callers or simulated personas against an agent variant." },
    ],
  },
  {
    label: "Feedback",
    items: [
      { to: "/review", label: "Review", icon: ListChecks, spec: "007", blurb: "A queue of calls to label, so evaluators can be checked against people." },
      { to: "/calibration", label: "Calibration", icon: Crosshair, spec: "007", blurb: "How far each evaluator agrees with human labels, and where it drifts." },
      { to: "/issues", label: "Issues", icon: WarningDiamond, spec: "009", blurb: "Recurring failures grouped into issues, each with a drafted and validated fix." },
    ],
  },
];

export const BILLING_ITEM: NavItem = {
  to: "/billing",
  label: "Billing",
  icon: CreditCard,
  spec: "001",
  blurb: "Balance, top-ups, transactions and usage.",
};

export const ALL_NAV_ITEMS: NavItem[] = [...NAV.flatMap((g) => g.items), BILLING_ITEM];
