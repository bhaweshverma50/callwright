import { Globe, Grid3x3, PhoneForwarded, PhoneOff } from "lucide-react";
import type { ReactNode } from "react";
import type { ConfigByType, ToolType } from "../../../api/tools";
import { cn } from "../../../components";

export interface ToolTypeMeta {
  label: string;
  /** One line for pickers. */
  summary: string;
  icon: ReactNode;
  /** Tile tint for the type (filled shape, never a stripe). */
  tile: string;
  namePlaceholder: string;
  descriptionPlaceholder: string;
}

export const TOOL_META: Record<ToolType, ToolTypeMeta> = {
  end_call: {
    label: "End call",
    summary: "Says goodbye and hangs up when the caller is done.",
    icon: <PhoneOff aria-hidden />,
    tile: "bg-danger-soft text-danger-text",
    namePlaceholder: "end_call",
    descriptionPlaceholder: "End the call when the caller says goodbye or has nothing else to ask",
  },
  transfer_call: {
    label: "Transfer call",
    summary: "Hands the caller to a person, cold or with a briefing.",
    icon: <PhoneForwarded aria-hidden />,
    tile: "bg-success-soft text-success-text",
    namePlaceholder: "transfer_to_front_desk",
    descriptionPlaceholder: "Transfer the caller to the front desk when they ask for a person",
  },
  press_digit: {
    label: "Press digits",
    summary: "Sends keypad tones to navigate a phone menu.",
    icon: <Grid3x3 aria-hidden />,
    tile: "bg-warning-soft text-warning-text",
    namePlaceholder: "press_digit",
    descriptionPlaceholder: "Press keypad digits to navigate a phone menu",
  },
  http: {
    label: "HTTP request",
    summary: "Calls your API with typed parameters and reads the answer.",
    icon: <Globe aria-hidden />,
    tile: "bg-accent-soft text-accent-text",
    namePlaceholder: "check_availability",
    descriptionPlaceholder: "Look up free appointment slots for a date",
  },
};

export const TOOL_TYPES: ToolType[] = ["http", "transfer_call", "end_call", "press_digit"];

export function ToolTile({ type, size = "md", className }: { type: ToolType; size?: "sm" | "md" | "lg"; className?: string }) {
  const meta = TOOL_META[type];
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-control",
        size === "sm" ? "size-8 [&_svg]:size-4" : size === "lg" ? "size-11 [&_svg]:size-[22px]" : "size-10 [&_svg]:size-5",
        meta.tile,
        className,
      )}
    >
      {meta.icon}
    </span>
  );
}

export const DEFAULT_CONFIGS: ConfigByType = {
  end_call: { message: "Thanks for calling. Goodbye!" },
  transfer_call: {
    routing_type: "static",
    number: "",
    routing_instructions: "",
    allowed_numbers: [],
    transfer_type: "cold",
    warm_transfer: null,
    hold_message: "Please hold while I connect you.",
    ring_timeout_s: 30,
  },
  press_digit: { delay_ms: 1000, cooldown_ms: 5000 },
  http: {
    method: "POST",
    url: "",
    parameters: { type: "object", properties: {}, required: [] },
    headers: [{ name: "Content-Type", value: "application/json", secret: false }],
    body_template: null,
    timeout_ms: 8000,
    response_mappings: [],
    speak_during_execution: true,
    execution_message: "One moment while I check that.",
  },
};
