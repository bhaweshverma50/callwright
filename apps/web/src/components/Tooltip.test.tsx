import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TOOLTIP_DELAY_MS, Tooltip, TooltipProvider } from "./Tooltip";

function Nav({ enabled }: { enabled: boolean }) {
  return (
    <TooltipProvider>
      <Tooltip content="Dashboard tip" side="right" enabled={enabled}>
        <button type="button">Dashboard</button>
      </Tooltip>
    </TooltipProvider>
  );
}

describe("Tooltip", () => {
  it("does not open tips hovered while disabled once it is enabled (sidebar collapse)", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Nav enabled={false} />);
    await user.hover(screen.getByRole("button", { name: "Dashboard" }));
    // Stay past the open delay, as a pointer resting on a nav item would.
    await new Promise((r) => setTimeout(r, TOOLTIP_DELAY_MS + 100));
    await user.unhover(screen.getByRole("button", { name: "Dashboard" }));
    rerender(<Nav enabled />);
    expect(screen.queryByText("Dashboard tip")).not.toBeInTheDocument();
  });
});
