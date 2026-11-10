import {
  AudioLines,
  Bot,
  Gauge,
  LayoutTemplate,
  ListChecks,
  CircleCheckBig,
  PhoneCall,
  PhoneForwarded,
  Rocket,
  ScrollText,
  type LucideIcon,
} from "lucide-react";
import {
  agentEditPath,
  AGENTS_PATH,
  agentTestingPath,
  CALLS_PATH,
  isAgentId,
  NEW_AGENT_PATH,
  PHONE_NUMBERS_PATH,
  REVIEW_PATH,
  TEMPLATES_PATH,
} from "../../lib/paths";

/**
 * The guided setup tour (spec 013): one step per control on the way from an empty workspace to
 * an agent on a number. Each step names where it happens, what it points at (CSS selectors, the
 * first visible match wins) and, when it asks for an action, how to tell the user did it.
 *
 * Selectors use what the pages already render (ids, ARIA names, Radix ids) and only fall back to
 * `data-tour` anchors where nothing stable exists.
 */

export type StepId = "agents" | "template" | "prompt" | "voice" | "cost" | "test-call" | "publish" | "channels" | "calls" | "quality" | "done";

export interface TourEnv {
  pathname: string;
  search: string;
  doc: Document;
}

export interface TourStep {
  id: StepId;
  title: string;
  body: string;
  icon: LucideIcon;
  /** Where the step happens. `agentId` is the agent the tour follows. Null keeps the page. */
  path: (agentId: string) => string | null;
  /** The path needs the agent the tour follows. */
  needsAgent?: boolean;
  /** Also require an empty query string (a tab param would hide the target). */
  exactSearch?: boolean;
  /** Candidates for the highlighted control, in order. */
  target?: string[];
  /** Candidates below 640 px, where the popover is a bottom sheet and a tall target would sit under it. */
  sheetTarget?: string[];
  /** The real action that completes the step. Checked only once the step's page is open. */
  doneWhen?: (env: TourEnv) => boolean;
  /** What the popover says while it waits for that action. */
  waitingFor?: string;
  /** "Do it for me": click this control, or run a tour action. */
  doIt?: { label: string; click?: string; action?: "create-agent" };
}

export const STEPS: TourStep[] = [
  {
    id: "agents",
    title: "Start with an agent",
    body: "An agent answers and places calls with your prompt, a language model and a voice. Templates come with all three, written for your industry.",
    icon: Bot,
    path: () => AGENTS_PATH,
    target: ["a[href='/agents/templates']"],
    doneWhen: ({ pathname }) => pathname === TEMPLATES_PATH || pathname.startsWith(NEW_AGENT_PATH),
    waitingFor: "Open the templates to go on",
    doIt: { label: "Open templates", click: "a[href='/agents/templates']" },
  },
  {
    id: "template",
    title: "Pick a template",
    body: "Open any template to read its greeting and prompt, then choose Use template. The agent is saved as version 1, ready to change.",
    icon: LayoutTemplate,
    path: () => "/agents/templates",
    target: ["[data-tour='template-grid']"],
    sheetTarget: ["[data-tour='template-grid'] > button"],
    doneWhen: ({ pathname }) => pathname.endsWith("/edit") && agentInPath(pathname) !== null,
    waitingFor: "Use a template to go on",
    doIt: { label: "Choose one for me", action: "create-agent" },
  },
  {
    id: "prompt",
    title: "Tell it what to do",
    body: "The prompt is the agent's brief: who it is, what it helps with and when to hand over. The template's prompt works as it is; change it whenever you like.",
    icon: ScrollText,
    path: agentEditPath,
    needsAgent: true,
    exactSearch: true,
    target: ["#f-prompt"],
  },
  {
    id: "voice",
    title: "Choose how it sounds",
    body: "The Voice tab lets you hear samples and pick the voice callers will hear. Speech recognition and the model sit on the other tabs.",
    icon: AudioLines,
    path: agentEditPath,
    needsAgent: true,
    target: ["[role='tab'][id$='-trigger-voice']"],
    doneWhen: ({ doc }) => Boolean(doc.querySelector("[role='tab'][id$='-trigger-voice'][aria-selected='true']")),
    waitingFor: "Open the Voice tab to go on",
    doIt: { label: "Open the Voice tab", click: "[role='tab'][id$='-trigger-voice']" },
  },
  {
    id: "cost",
    title: "See the price per minute",
    body: "Every link of the chain shows its rate. The total is what one minute of a call costs on this stack, and it moves as you change the model or the voice.",
    icon: Gauge,
    path: agentEditPath,
    needsAgent: true,
    target: ["section[aria-labelledby='cost-title']"],
  },
  {
    id: "test-call",
    title: "Talk to it",
    body: "Start a test call and speak. It rings first, then each answer lands in the transcript with a latency chip that splits the wait by link of the chain.",
    icon: PhoneCall,
    path: agentTestingPath,
    needsAgent: true,
    target: ["section[aria-label='Test call']"],
    sheetTarget: ["section[aria-label='Test call'] footer"],
    doneWhen: ({ doc }) => Boolean(doc.querySelector("section[aria-label='Test call'][data-phase='ended']")),
    waitingFor: "End the call to go on",
    doIt: { label: "Start the call", click: "section[aria-label='Test call'][data-phase='idle'] footer button" },
  },
  {
    id: "publish",
    title: "Publish it",
    body: "Publishing makes the saved version live. Numbers and WhatsApp answer with the published version; later edits stay in draft until you publish again.",
    icon: Rocket,
    path: agentEditPath,
    needsAgent: true,
    target: ["[data-tour='agent-publish']"],
    doneWhen: ({ doc }) => Boolean(doc.querySelector("[data-tour='agent-publish'][data-published='true']")),
    waitingFor: "Publish to go on",
    doIt: { label: "Publish for me", click: "[data-tour='agent-publish'] button:not([disabled])" },
  },
  {
    id: "channels",
    title: "Put it on a number",
    body: "Import a number from your SIP trunk and choose this agent to answer it. No carrier yet? A test line on a lab PBX works the same way, and unanswered calls are never charged.",
    icon: PhoneForwarded,
    path: () => PHONE_NUMBERS_PATH,
    target: ["[data-tour='channels-import']", "[role='tabpanel'][id$='-content-numbers']"],
  },
  {
    id: "calls",
    title: "Find every call",
    body: "Calls land here as they end. Open one for the transcript, the recording, a summary, the latency of every turn and the itemised cost.",
    icon: PhoneCall,
    path: () => CALLS_PATH,
    target: ["section[aria-label='Call history']", "main h1"],
  },
  {
    id: "quality",
    title: "Check the quality",
    body: "Automatic checks score every call. Review is a queue of calls for people to label, so you can see where the checks agree with you and where they drift.",
    icon: ListChecks,
    path: () => REVIEW_PATH,
    target: ["[role='tablist'][aria-label='Queue']"],
  },
  {
    id: "done",
    title: "Your agent is set up",
    body: "That is the whole path from a template to a live agent. Pick up wherever you like.",
    icon: CircleCheckBig,
    path: () => null,
  },
];

/** Steps that count towards "Step n of N" (the recap is not one). */
export const COUNTED = STEPS.length - 1;

export function stepIndex(id: string | null | undefined): number {
  const i = STEPS.findIndex((s) => s.id === id);
  return i < 0 ? 0 : i;
}

/** The step's address with the agent filled in, or null when it needs an agent it does not have. */
export function stepPath(step: TourStep, agentId: string | null): string | null {
  if (step.needsAgent && !agentId) return null;
  return step.path(agentId ?? "");
}

/** True when the page shows the step's address (and, for exact steps, no query string). */
export function onStepPage(step: TourStep, path: string | null, loc: { pathname: string; search: string }): boolean {
  if (path === null) return true;
  return loc.pathname === path && (!step.exactSearch || loc.search === "" || loc.search === "?");
}

/** The agent id in an agent page's address, if any. */
export function agentInPath(pathname: string): string | null {
  const id = /^\/agents\/([^/]+)\/(edit|testing)$/.exec(pathname)?.[1];
  return id && isAgentId(id) ? id : null;
}
