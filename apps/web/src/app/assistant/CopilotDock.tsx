import { motion } from "motion/react";
import { cn } from "../../components";
import { VoiceCopilot } from "../copilot/VoiceCopilot";
import { AskPanel } from "./AskPanel";

/** Full-height editors where a floating dock would sit on the canvas: the dock moves into the top bar. */
export function isFullHeightEditor(pathname: string): boolean {
  return /^\/agents\/[^/]+\/flow\/?$/.test(pathname);
}

/**
 * The shell's assistant controls (spec 006): type a command, talk to the voice copilot and "Ask
 * about your data", in one compact capsule. `dock` floats at the bottom right (the shell reserves
 * room for it at the end of every page); `bar` sits in the top bar on full-height editors, where
 * Space already pans the canvas, so push-to-talk there is the mic button only. Neither requests
 * a credential until it is used (FR-020).
 */
export function CopilotDock({ placement = "dock" }: { placement?: "dock" | "bar" }) {
  const bar = placement === "bar";
  return (
    <motion.div
      role="group"
      aria-label="Assistant"
      initial={{ opacity: 0, y: bar ? -6 : 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "flex items-center gap-0.5 rounded-full border border-line",
        bar ? "relative bg-surface p-0.5" : "fixed bottom-4 right-4 z-40 bg-surface/90 p-1 shadow-pop backdrop-blur-md",
      )}
    >
      <VoiceCopilot placement={placement} spaceToTalk={!bar} />
      <span aria-hidden className="mx-1 h-5 w-px bg-line" />
      <AskPanel placement={placement} />
    </motion.div>
  );
}
