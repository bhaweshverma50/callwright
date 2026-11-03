import type { OnboardingStatus } from "../../api/types";
import { STEPS, stepIndex } from "./steps";

/**
 * The tour as a pure reducer (spec 013). `status` is what the server stores; `phase` is what the
 * screen shows:
 *
 * - `idle`: nothing on screen (not started and not offered, skipped or completed).
 * - `offer`: the welcome card (only for a user who has not started or skipped).
 * - `running`: spotlight and popover on `STEPS[index]`.
 * - `paused`: the resume chip; the server still says `in_progress` at this step.
 */
export type Phase = "idle" | "offer" | "running" | "paused";

export interface TourState {
  status: OnboardingStatus;
  phase: Phase;
  index: number;
  /** The server state has been read; nothing is saved before that. */
  loaded: boolean;
}

export type TourEvent =
  | { type: "load"; status: OnboardingStatus; step: string | null }
  | { type: "offer" }
  | { type: "start" }
  | { type: "decline" }
  | { type: "next" }
  | { type: "back" }
  | { type: "goto"; step: string }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "skip" }
  | { type: "finish" };

export const initialTour: TourState = { status: "not_started", phase: "idle", index: 0, loaded: false };

const LAST = STEPS.length - 1;

export function tourReducer(s: TourState, e: TourEvent): TourState {
  switch (e.type) {
    case "load":
      if (s.loaded) return s;
      // A tour in progress comes back paused at its step: the user chooses to resume.
      return {
        status: e.status,
        phase: e.status === "in_progress" ? "paused" : "idle",
        index: e.status === "completed" ? LAST : stepIndex(e.step),
        loaded: true,
      };
    case "offer":
      return s.loaded && s.phase === "idle" && s.status === "not_started" ? { ...s, phase: "offer" } : s;
    case "start":
      // From the welcome card or the account menu: always the first step.
      return { ...s, status: "in_progress", phase: "running", index: 0 };
    case "decline":
      return s.phase === "offer" ? { ...s, status: "skipped", phase: "idle" } : s;
    case "next":
      if (s.phase !== "running") return s;
      return s.index >= LAST ? { ...s, status: "completed", phase: "idle" } : { ...s, index: s.index + 1 };
    case "back":
      return s.phase === "running" ? { ...s, index: Math.max(0, s.index - 1) } : s;
    case "goto":
      return s.phase === "running" ? { ...s, index: stepIndex(e.step) } : s;
    case "pause":
      return s.phase === "running" ? { ...s, phase: "paused" } : s;
    case "resume":
      return s.phase === "paused" ? { ...s, status: "in_progress", phase: "running" } : s;
    case "skip":
      return s.phase === "running" || s.phase === "paused" ? { ...s, status: "skipped", phase: "idle" } : s;
    case "finish":
      return s.phase === "running" ? { ...s, status: "completed", phase: "idle", index: LAST } : s;
  }
}

/** What the server should hold for this state: the status and the current step id. */
export function persisted(s: TourState): { status: OnboardingStatus; step: string | null } {
  if (s.status === "not_started") return { status: "not_started", step: null };
  return { status: s.status, step: STEPS[s.index]!.id };
}
