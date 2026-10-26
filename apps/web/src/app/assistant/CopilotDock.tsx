import { VoiceCopilot } from "../copilot/VoiceCopilot";
import { AskPanel } from "./AskPanel";

/**
 * The two shell overlays (spec 006): the voice copilot and the "Ask about your data" launcher sit
 * together at the bottom right; the Ask panel opens over the page. Neither requests a credential
 * until it is used (FR-020).
 */
export function CopilotDock() {
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-40 flex items-center gap-2 [&>*]:pointer-events-auto">
      <VoiceCopilot />
      <AskPanel />
    </div>
  );
}
