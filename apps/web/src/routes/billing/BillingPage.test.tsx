import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp, signInDemo } from "../../test/render";
import { defaultWindow, windowError } from "./UsagePanel";

describe("transactions (T058, FR-009)", () => {
  it("lists 20 rows per page, newest first, with pagination", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/billing");
    const table = await screen.findByRole("table", { name: "Credit transactions, newest first" });
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(21));
    const times = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelector("time")!.getAttribute("datetime")!);
    expect([...times].sort().reverse()).toEqual(times);
    expect(screen.getByText(/1 to 20 of \d+ transactions/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/21 to \d+ of \d+ transactions/)).toBeInTheDocument();
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
