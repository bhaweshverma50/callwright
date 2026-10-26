import { Braces, ClipboardList, GitBranch, Globe, Megaphone, PhoneForwarded, PhoneOff, Play, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import type { NodeType } from "../../../api/flows";

export interface NodeMeta {
  title: string;
  /** One line for the palette and the empty side panel. */
  blurb: string;
  icon: ReactNode;
}

export const NODE_META: Record<NodeType, NodeMeta> = {
  start: { title: "Start", blurb: "Who speaks first and the greeting", icon: <Play aria-hidden /> },
  agent: { title: "Agent", blurb: "A conversation with its own instructions", icon: <Sparkles aria-hidden /> },
  task: { title: "Task", blurb: "Collects named details from the caller", icon: <ClipboardList aria-hidden /> },
  condition: { title: "Condition", blurb: "Routes by category or by rule, silently", icon: <GitBranch aria-hidden /> },
  say: { title: "Say", blurb: "Speaks a fixed line without the model", icon: <Megaphone aria-hidden /> },
  extract_variable: { title: "Extract", blurb: "Saves values from the conversation", icon: <Braces aria-hidden /> },
  webhook: { title: "API call", blurb: "Calls an outside system", icon: <Globe aria-hidden /> },
  transfer: { title: "Transfer", blurb: "Hands the caller to a person", icon: <PhoneForwarded aria-hidden /> },
  end: { title: "End", blurb: "Closes the call with a reason", icon: <PhoneOff aria-hidden /> },
};

/** Palette order: the steps most flows use first. */
export const PALETTE: NodeType[] = ["agent", "task", "condition", "say", "extract_variable", "webhook", "transfer", "end", "start"];

/** Drag payload type when a palette tile is dropped on the canvas. */
export const DRAG_TYPE = "application/x-callwright-node";
