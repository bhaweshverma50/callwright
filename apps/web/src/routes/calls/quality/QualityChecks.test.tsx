import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { env } from "../../../lib/env";
import { server } from "../../../mocks/node";
import { mockCallId, seedMockCalls } from "../../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../../test/render";

async function openQuality(n: number) {
  seedMockCalls(45);
  await signInDemo();
  renderApp(`/calls?call=${mockCallId(n)}&tab=quality`);
  return screen.findByRole("dialog", undefined, { timeout: 5000 });
}

describe("QualityChecks (007 T043, US2)", () => {
  it("groups results by check with counts, versions, reasons and per-turn rows", async () => {
    const user = userEvent.setup();
    const drawer = await openQuality(8); // Order desk, intent and latency fail
    expect(await within(drawer).findByText("2 failed", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(drawer).getByText("2 passed")).toBeInTheDocument();
    const results = within(drawer).getByRole("list", { name: "Check results" });
    expect(within(results).getByText(/never confirmed the change/)).toBeInTheDocument();
    expect(within(results).getAllByText("v2").length).toBeGreaterThan(0);
    const latency = within(results).getByRole("button", { name: /Turn latency/ });
    expect(within(latency).getByText("1 of 6 turns failed")).toBeInTheDocument();
    const rows = within(results).getByRole("list", { name: "Turn latency results" });
    for (let t = 1; t <= 6; t++) expect(within(rows).getByText(`Turn ${t}`)).toBeInTheDocument();
    await user.click(latency);
    expect(within(results).queryByRole("list", { name: "Turn latency results" })).not.toBeInTheDocument();
  });

  it("says no issues were detected on a clean call", async () => {
    const drawer = await openQuality(0);
    expect(await within(drawer).findByText("No issues detected", undefined, { timeout: 5000 })).toBeInTheDocument();
  });

  it("shows the running state for a call still processing", async () => {
    const drawer = await openQuality(3);
    expect(await within(drawer).findByText("Running checks, results appear as each one finishes", undefined, { timeout: 5000 })).toBeInTheDocument();
  });

  it("re-runs once, refuses a second re-run while the first runs, and keeps history", async () => {
    const user = userEvent.setup();
    const drawer = await openQuality(4);
    const rerun = await within(drawer).findByRole("button", { name: "Re-run checks" }, { timeout: 5000 });
    await user.click(rerun);
    expect(await within(drawer).findByText("Running checks, results appear as each one finishes")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: /History \(4 earlier results\)/ })).toBeInTheDocument();
    // The button is disabled while running; the API refuses a direct second request too.
    expect(within(drawer).getByRole("button", { name: "Re-run checks" })).toBeDisabled();
  });
});

describe("QualityChecks refusals", () => {
  it('says "Checks are already running" when the API refuses a re-run', async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${env.apiBaseUrl}/calls/:id/evaluations/rerun`, () =>
        HttpResponse.json(
          {
            type: "https://callwright.dev/problems/checks-running",
            title: "Checks are already running",
            status: 409,
            code: "checks_running",
            detail: "Checks are already running",
          },
          { status: 409, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    const drawer = await openQuality(4);
    await user.click(await within(drawer).findByRole("button", { name: "Re-run checks" }, { timeout: 5000 }));
    expect(await within(drawer).findByText("Checks are already running")).toBeInTheDocument();
    expect(within(drawer).getByText("No issues detected")).toBeInTheDocument();
  });
});

describe("YourReview (007 T047, US3)", () => {
  it("labels good with a note, switches to bad, then clears after confirming", async () => {
    const user = userEvent.setup();
    const drawer = await openQuality(0);
    const group = await within(drawer).findByRole("group", { name: "Your label" }, { timeout: 5000 });
    await user.type(within(drawer).getByLabelText(/^Note/), "clean booking");
    await user.click(within(group).getByRole("button", { name: "Good" }));
    await waitFor(() => expect(within(group).getByRole("button", { name: "Good" })).toHaveAttribute("aria-pressed", "true"));
    expect(within(drawer).getByLabelText(/^Note/)).toHaveValue("clean booking");
    await user.click(within(group).getByRole("button", { name: "Bad" }));
    await waitFor(() => expect(within(group).getByRole("button", { name: "Bad" })).toHaveAttribute("aria-pressed", "true"));
    expect(within(group).getByRole("button", { name: "Good" })).toHaveAttribute("aria-pressed", "false");
    await user.click(within(group).getByRole("button", { name: "Bad" }));
    const confirm = await screen.findByRole("alertdialog");
    await user.click(within(confirm).getByRole("button", { name: "Remove label" }));
    await waitFor(() => expect(within(group).getByRole("button", { name: "Bad" })).toHaveAttribute("aria-pressed", "false"));
  });

  it("refuses a note over 2,000 characters", async () => {
    const user = userEvent.setup();
    const drawer = await openQuality(0);
    await within(drawer).findByRole("group", { name: "Your label" }, { timeout: 5000 });
    const note = within(drawer).getByLabelText(/^Note/);
    await user.click(note);
    await user.paste("x".repeat(2001));
    expect(within(drawer).getByText("Keep the note under 2,000 characters.")).toBeInTheDocument();
  });

  it("shows a teammate's label with their name", async () => {
    const drawer = await openQuality(24);
    expect(await within(drawer).findByText("Priya Raman", undefined, { timeout: 5000 })).toBeInTheDocument();
  });
});

describe("CallAnalysisPanel (007 US1)", () => {
  it("shows values, not found and renamed variables", async () => {
    seedMockCalls(45);
    await signInDemo();
    renderApp(`/calls?call=${mockCallId(40)}&tab=analysis`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    expect(await within(drawer).findByText("order_found", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(drawer).getByText("(renamed)")).toBeInTheDocument();
    expect(within(drawer).getByText(/Extracted with/)).toBeInTheDocument();
    expect(within(drawer).getAllByText("not found").length).toBeGreaterThan(0);
    expect(within(drawer).getByRole("button", { name: "Re-run analysis" })).toBeInTheDocument();
  });
});
