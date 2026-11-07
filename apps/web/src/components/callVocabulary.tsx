/** Names, tones and badges for the call vocabulary (statuses, channels, end reasons, sentiment, origins, checks). */
import { CircleHelp, Frown, Meh, PhoneCall, Smile } from "lucide-react";
import type { CallOrigin, CallStatus, Channel, DisconnectReason, EvalStatus, Sentiment } from "../api/calls";
import { Badge, type Tone } from "./Badge";
import { OnAir } from "./signal";

export const STATUS_LABELS: Record<CallStatus, string> = {
  queued: "Queued",
  ringing: "Ringing",
  in_progress: "In progress",
  ended: "Ended",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
  no_answer: "No answer",
  busy: "Busy",
  voicemail: "Voicemail",
};

export const STATUS_TONES: Record<CallStatus, Tone> = {
  queued: "neutral",
  ringing: "accent",
  in_progress: "accent",
  ended: "neutral",
  processing: "accent",
  completed: "success",
  failed: "danger",
  no_answer: "warning",
  busy: "warning",
  voicemail: "neutral",
};

export const CHANNEL_LABELS: Record<Channel, string> = {
  web: "Web",
  sip_inbound: "Inbound phone",
  sip_outbound: "Outbound phone",
  whatsapp: "WhatsApp",
};

export const REASON_LABELS: Record<DisconnectReason, string> = {
  user_hangup: "Caller hung up",
  agent_hangup: "Agent ended",
  call_transfer: "Transferred",
  voicemail_reached: "Voicemail reached",
  inactivity: "Silence timeout",
  max_duration_reached: "Max duration",
  error: "Error",
  concurrency_limit: "Concurrency limit",
  insufficient_credit: "Out of credit",
};

export const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
  unknown: "Unknown",
};

export const SENTIMENT_TONES: Record<Sentiment, Tone> = {
  positive: "success",
  neutral: "neutral",
  negative: "danger",
  unknown: "neutral",
};

export const ORIGIN_LABELS: Record<CallOrigin, string> = { live: "Live", test: "Test", simulation: "Simulated" };

export const EVAL_LABELS: Record<EvalStatus, string> = {
  not_evaluated: "Not evaluated",
  running: "Running",
  passed: "Passed",
  failed: "Failed",
  error: "Error",
};

const SENTIMENT_ICONS = { positive: Smile, neutral: Meh, negative: Frown, unknown: CircleHelp } as const;

export function CallStatusBadge({ status }: { status: CallStatus }) {
  if (status === "in_progress") return <OnAir pill label="On air" className="whitespace-nowrap" />;
  if (status === "ringing")
    return (
      <Badge tone="accent" icon={<PhoneCall aria-hidden />}>
        Ringing
      </Badge>
    );
  return <Badge tone={STATUS_TONES[status]}>{STATUS_LABELS[status]}</Badge>;
}

export function SentimentBadge({ value }: { value: Sentiment | null | undefined }) {
  if (!value) return <span className="text-fg-3">n/a</span>;
  const Icon = SENTIMENT_ICONS[value];
  return (
    <Badge tone={SENTIMENT_TONES[value]} icon={<Icon aria-hidden />}>
      {SENTIMENT_LABELS[value]}
    </Badge>
  );
}
