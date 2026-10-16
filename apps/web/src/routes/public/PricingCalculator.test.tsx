import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "../../app/queryClient";
import { TooltipProvider } from "../../components";
import { MAX_MINUTES, PricingCalculator } from "./PricingCalculator";

function setup() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <PricingCalculator />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("PricingCalculator (T065, US3.4)", () => {
  it("shows the per-minute total from the quote and monthly = per-minute x minutes", async () => {
    setup();
    // Nova-3 0.0085 + GPT-5 Mini 0.0015 + Flash v2.5 0.0450 + platform 0.0500
    await waitFor(() => expect(screen.getByTestId("per-minute")).toHaveTextContent("$0.1050"));
    expect(screen.getByTestId("monthly")).toHaveTextContent("$1,050.00");

    fireEvent.change(screen.getByLabelText("Minutes per month", { selector: "input" }), { target: { value: "20,000" } });
    await waitFor(() => expect(screen.getByTestId("monthly")).toHaveTextContent("$2,100.00"));
  });

  it("caps minutes at 250,000 and exposes the slider range", async () => {
    setup();
    await screen.findByTestId("per-minute");
    const slider = screen.getByRole("slider", { name: "Minutes per month" });
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", String(MAX_MINUTES));
    fireEvent.change(screen.getByLabelText("Minutes per month", { selector: "input" }), { target: { value: "999999" } });
    await waitFor(() => expect(screen.getByTestId("monthly")).toHaveTextContent("$26,250.00"));
  });

  it("applies the bundle surcharge when usage per minute passes the bundle", async () => {
    setup();
    await waitFor(() => expect(screen.getByTestId("per-minute")).toHaveTextContent("$0.1050"));
    const tokens = screen.getByRole("slider", { name: "LLM input tokens per minute" });
    tokens.focus();
    // 12,000 -> 40,000 tokens per minute: 2x the 20,000 bundle, so the LLM line bills double.
    for (let i = 0; i < 28; i++) fireEvent.keyDown(tokens, { key: "ArrowRight" });
    expect(await screen.findByText("Bundle surcharge applies")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("per-minute")).toHaveTextContent("$0.1065"));
  });
});
