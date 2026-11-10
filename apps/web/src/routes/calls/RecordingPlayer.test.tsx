import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecordingPlayer } from "./RecordingPlayer";
import { TooltipProvider } from "../../components";

const ui = (props: { hasRecording: boolean; processing?: boolean }) => (
  <TooltipProvider>
    <RecordingPlayer callId="call_1" durationS={30} {...props} />
  </TooltipProvider>
);

describe("RecordingPlayer", () => {
  it("shows the recording once fresher call data says it finished uploading", () => {
    const { rerender } = render(ui({ hasRecording: false, processing: true }));
    expect(screen.queryByRole("button", { name: "Play recording" })).not.toBeInTheDocument();
    rerender(ui({ hasRecording: true, processing: false }));
    expect(screen.getByRole("button", { name: "Play recording" })).toBeInTheDocument();
  });

  it("says there is none when the call was not recorded", () => {
    render(ui({ hasRecording: false }));
    expect(screen.getByText("No recording for this call")).toBeInTheDocument();
  });
});
