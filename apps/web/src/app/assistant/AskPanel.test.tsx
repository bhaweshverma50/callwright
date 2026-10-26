import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockCalls } from "../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../test/render";
import { callsUrl } from "../copilot/VoiceCopilot";

async function openPanel() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Ask about your data" }));
  const panel = await screen.findByRole("dialog", { name: "Ask about your data" });
  return { user, panel };
}

describe("AskPanel (006 US5)", () => {
  it("answers with a table and how it was computed", async () => {
    await signInDemo();
    renderApp("/billing");
    const { user, panel } = await openPanel();
    await user.type(within(panel).getByLabelText("Your question"), "Cost by agent this month{Enter}");
    expect(await within(panel).findByText(/Total cost by agent/, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(panel).getByRole("cell", { name: "$1.200" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "How this was computed" }));
    expect(within(panel).getByText("total_cost_usd")).toBeInTheDocument();
  });

  it("names the cause, keeps the question and offers the next step", async () => {
    await signInDemo();
    renderApp("/billing");
    const { user, panel } = await openPanel();
    const box = within(panel).getByLabelText("Your question");
    await user.type(box, "Cost #402{Enter}");
    expect(await within(panel).findByRole("alert")).toHaveTextContent("out of credit");
    expect(within(panel).getByRole("link", { name: "Add funds" })).toHaveAttribute("href", "/billing");
    expect(box).toHaveValue("Cost #402");
    await user.clear(box);
    await user.type(box, "Cost #503{Enter}");
    expect(await within(panel).findByRole("alert")).toHaveTextContent("unavailable");
    expect(within(panel).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(box).toHaveValue("Cost #503");
  });

  it("reuses the request key when the same question is retried", async () => {
    await signInDemo();
    renderApp("/billing");
    const { user, panel } = await openPanel();
    const box = within(panel).getByLabelText("Your question");
    await user.type(box, "Cost #503{Enter}");
    await within(panel).findByRole("alert");
    await user.click(within(panel).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mockCalls().requests.filter((r) => r.startsWith("chat:"))).toHaveLength(2), { timeout: 5000 });
    const [a, b] = mockCalls().requests.filter((r) => r.startsWith("chat:"));
    expect(a).toBe(b);
  });

  it("offers example questions after a decline", async () => {
    await signInDemo();
    renderApp("/billing");
    const { user, panel } = await openPanel();
    await user.type(within(panel).getByLabelText("Your question"), "What is our churn rate?{Enter}");
    expect(await within(panel).findByText("I cannot answer that from your call data.", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(panel).getAllByRole("button", { name: "Busiest day last week" }).length).toBeGreaterThan(0);
  });
});

describe("voice copilot navigation (006 US6)", () => {
  it("turns a validated navigate result into Call History filters", () => {
    const now = new Date(2026, 9, 16, 10);
    expect(callsUrl({ status: ["failed"], date_range: "yesterday" }, now)).toBe("/calls?status=failed&start_date=2026-10-15&end_date=2026-10-15");
    expect(callsUrl(null, now)).toBe("/calls");
  });

  it("offers a typed command that runs the same interpretation", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/billing");
    await user.click(await screen.findByRole("button", { name: "Type a command" }));
    await user.type(screen.getByRole("textbox", { name: "Type a command" }), "show me failed calls from yesterday{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/calls"), { timeout: 5000 });
    expect(router.state.location.search).toContain("status=failed");
  });

  it("does not start push-to-talk while typing in a field", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/billing");
    const { panel } = await openPanel();
    const box = within(panel).getByLabelText("Your question");
    await user.type(box, "a b");
    expect(box).toHaveValue("a b");
    expect(screen.queryByText("Listening")).not.toBeInTheDocument();
  });
});
