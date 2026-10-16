/**
 * A sample call used by the home hero and the sign-in panel: a dental front desk agent moving an
 * appointment. Times are seconds from the start of the call; latency is per agent turn, split by
 * link of the chain (speech to text, model, voice) in milliseconds.
 */
import type { Latency } from "../components/signal";

export interface SampleTurn {
  who: "caller" | "agent";
  text: string;
  at: number;
  latency?: Latency;
}

export const SAMPLE_CALL: SampleTurn[] = [
  { who: "caller", text: "Hi, I need to move my cleaning on Tuesday. Something came up at work.", at: 0 },
  { who: "agent", text: "No problem. I can see your 9:30 with Dr. Okafor. Thursday has 10:40 or 2:15. Which works?", at: 4.2, latency: { stt: 160, llm: 310, tts: 140 } },
  { who: "caller", text: "2:15 is good.", at: 9.8 },
  { who: "agent", text: "Done. You're booked for Thursday at 2:15. I'll text you a reminder the day before.", at: 11.6, latency: { stt: 150, llm: 280, tts: 130 } },
];

export const SAMPLE_CALL_SECONDS = 16;
