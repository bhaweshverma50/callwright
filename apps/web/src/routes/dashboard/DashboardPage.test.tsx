import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { seedMockCalls } from "../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../test/render";
import { rangeError, readSelection } from "./DashboardPage";
import { setupSteps, toStepperSteps } from "./DashboardPlaceholder";

describe("dashboard selection (FR-039, FR-040)", () => {
  it("applies a custom range only when both dates are valid and in order", () => {
    const base = readSelection(new URLSearchParams("period=custom"));
    expect(rangeError(base)).toBe("Pick a start and an end date.");
    expect(rangeError({ ...base, start: "2026-10-10", end: "2026-10-01" })).toBe("End date must be on or after start date.");
    expect(rangeError({ ...base, start: "2026-10-01", end: "2026-10-10" })).toBeNull();
    expect(readSelection(new URLSearchParams("period=bogus")).period).toBe("last_30_days");
  });
});

describe("setup sequence", () => {
  it("marks the agent step done once an agent exists and moves on to the test call", () => {
    expect(toStepperSteps(setupSteps()).map((s) => s.status)).toEqual(["active", "pending", "pending"]);
    expect(toStepperSteps(setupSteps({ hasAgent: true })).map((s) => s.status)).toEqual(["done", "active", "pending"]);
    expect(toStepperSteps(setupSteps({ hasAgent: true, hasTestCall: true })).map((s) => s.status)).toEqual(["done", "done", "active"]);
    expect(toStepperSteps(setupSteps({ hasAgent: true, hasTestCall: true, hasNumber: true })).map((s) => s.status)).toEqual(["done", "done", "done"]);
  });
});

describe("DashboardPage (006 US3)", () => {
  it("keeps the setup sequence while the workspace has no calls", async () => {
    await signInDemo();
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: "Get your first call on the line" })).toBeInTheDocument();
  });

  it("shows KPIs, applies a preset without an apply step, and clears back to defaults", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    const kpis = await screen.findByRole("region", { name: /Key figures/ });
    await waitFor(() => expect(kpis).toHaveTextContent("1.43 a day on average"), { timeout: 5000 });
    expect(screen.getByText("No evaluator runs in this period.")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "7d" }));
    await waitFor(() => expect(router.state.location.search).toBe("?period=last_7_days"), { timeout: 5000 });
    const chips = screen.getByRole("group", { name: "Active selection" });
    expect(within(chips).getByText("Last 7 days")).toBeInTheDocument();
    await user.click(within(chips).getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(router.state.location.search).toBe(""), { timeout: 3000 });
  });

  it("rejects a custom range that ends before it starts", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/dashboard");
    await user.click(await screen.findByRole("radio", { name: "Custom" }));
    await user.type(screen.getByLabelText("Start date"), "2026-10-10");
    await user.type(screen.getByLabelText("End date"), "2026-10-01");
    expect(await screen.findByRole("alert")).toHaveTextContent("End date must be on or after start date.");
  });

  it("refreshes every section and shows when it was updated", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/dashboard");
    const updated = await screen.findByText(/^Updated/, undefined, { timeout: 5000 });
    const before = updated.textContent;
    // The stamp shows seconds: move the clock on instead of waiting for it.
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(Date.now() + 2_000);
      await user.click(screen.getByRole("button", { name: "Refresh" }));
      await waitFor(() => expect(screen.getByText(/^Updated/).textContent).not.toBe(before));
    } finally {
      vi.useRealTimers();
    }
  });
});
