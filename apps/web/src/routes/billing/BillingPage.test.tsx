import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp, signInDemo } from "../../test/render";
import type { Transaction } from "../../api/types";
import { talkTimeFacts } from "./TalkTimeGauge";
import { defaultWindow, windowError } from "./UsagePanel";

describe("transactions (T058, FR-009)", () => {
  it("lists 20 rows per page, newest first, grouped by day, with pagination", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/billing");
    const timeline = await screen.findByRole("region", { name: "Credit transactions, newest first" });
    await waitFor(() => expect(within(timeline).getAllByRole("listitem")).toHaveLength(20));
    const times = within(timeline)
      .getAllByRole("listitem")
      .map((r) => r.querySelector("time")!.getAttribute("datetime")!);
    expect([...times].sort().reverse()).toEqual(times);
    expect(within(timeline).getAllByRole("heading", { level: 3 }).length).toBeGreaterThan(1);
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    expect(pager).toHaveTextContent(/1 to 20 of \d+ transactions/);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(pager).toHaveTextContent(/21 to \d+ of \d+ transactions/));
  });

  it("opens a call charge's cost breakdown", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/billing");
    const timeline = await screen.findByRole("region", { name: "Credit transactions, newest first" });
    const call = (await within(timeline).findAllByRole("button", { name: /Show cost breakdown$/ }))[0]!;
    await user.click(call);
    const drawer = await screen.findByRole("dialog", { name: "Cost breakdown" });
    expect(within(drawer).getByRole("region", { name: "Receipt" })).toHaveTextContent(/Total/);
  });

  it("states the balance as talk time on the default stack", async () => {
    await signInDemo();
    renderApp("/billing");
    expect(await screen.findByText("minutes of calls")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/On your current stack: Nova-3, GPT-5 Mini and Flash v2.5/)).toHaveTextContent("$0.1050"));
  });
});

describe("talk time (docs/DESIGN.md section 6)", () => {
  const now = new Date("2026-10-16T12:00:00Z");
  const row = (daysAgo: number, type: Transaction["type"], amount: string, after: string): Transaction =>
    ({
      id: `txn_${daysAgo}_${type}`,
      type,
      amount_usd: amount,
      balance_after_usd: after,
      created_at: new Date(now.getTime() - daysAgo * 86_400_000).toISOString(),
      description: "",
      call_id: null,
      feature_key: null,
      cost_breakdown: null,
    }) as Transaction;

  it("turns balance into whole minutes and projects the run-out from 14 days of spend", () => {
    const f = talkTimeFacts(14_000_000n, 105_000n, [row(1, "call_charge", "-7.000000", "14.000000"), row(20, "top_up", "21.000000", "21.000000")], now);
    expect(f.minutes).toBe(133);
    expect(f.perDayMicros).toBe(500_000n);
    expect(f.runOut?.toISOString()).toBe("2026-11-13T12:00:00.000Z");
    expect(f.fill).toBeCloseTo(14 / 21, 3);
  });

  it("has no run-out date without recent spend", () => {
    const f = talkTimeFacts(5_000_000n, 105_000n, [row(40, "call_charge", "-1.000000", "5.000000")], now);
    expect(f.runOut).toBeNull();
    expect(f.minutes).toBe(47);
    expect(f.fill).toBe(1);
  });
});

describe("usage window (T080, US4)", () => {
  it("defaults to the last 30 days and refuses bad windows", () => {
    const w = defaultWindow(new Date("2026-10-16T12:00:00Z"));
    expect(w).toEqual({ from: "2026-09-16", to: "2026-10-16" });
    expect(windowError("2026-10-10", "2026-10-01")).toBe("The end date must be on or after the start date.");
    expect(windowError("2025-01-01", "2026-10-01")).toBe("Pick a window of 366 days or less.");
    expect(windowError("2026-01-01", "2026-12-31")).toBeNull();
  });

  it("shows the empty state with the window dates", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/billing?tab=usage");
    const from = await screen.findByLabelText("From");
    const to = screen.getByLabelText("To");
    await user.clear(to);
    await user.type(to, "2020-01-31");
    await user.clear(from);
    await user.type(from, "2020-01-01");
    expect(await screen.findByText("No usage charges yet in this window")).toBeInTheDocument();
    const empty = screen.getByText("No usage charges yet in this window").parentElement!;
    expect(empty).toHaveTextContent(/1, 2020|1 Jan 2020/);
    expect(empty).toHaveTextContent(/31, 2020|31 Jan 2020/);
  });
});
