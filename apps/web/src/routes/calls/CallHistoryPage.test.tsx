import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockCalls, mockCallId, MOCK_AGENTS, seedMockCalls } from "../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../test/render";
import { emptyFilters, filterChips, parseListState, toApiQuery, toSearchParams } from "./filters";
import { checkSimulation } from "./selection";

const rowsOnPage = () => within(screen.getByRole("table")).getAllByRole("checkbox", { name: /^Select call / });

describe("call list URL state (FR-005, FR-036 to FR-038)", () => {
  it("drops unknown values and counts one chip per applied filter, Any not counted", () => {
    const { state, dropped } = parseListState(
      new URLSearchParams("status=failed,exploded&agent_id=agt_01HMCKAGENT0RDERDESK000001&label=good&origin=live,test"),
    );
    expect(dropped).toEqual(["exploded"]);
    const chips = filterChips(state.filters, (id) => (id === "agt_01HMCKAGENT0RDERDESK000001" ? "Order desk" : id));
    expect(chips.map((c) => c.label)).toEqual(["Status: Failed", "Agent: Order desk", "Your label: Good"]);
    const any = filterChips({ ...emptyFilters(), label: [] }, (id) => id);
    expect(any).toHaveLength(0);
  });

  it("keeps the plus sign and sends dates with the timezone", () => {
    const { state } = parseListState(new URLSearchParams("from_number=%2B1555&start_date=2026-10-01&end_date=2026-10-01"));
    const q = toApiQuery(state, "Asia/Kolkata");
    expect(q.toString()).toContain("from_number=%2B1555");
    expect(q.get("tz")).toBe("Asia/Kolkata");
    expect(q.get("start_date")).toBe("2026-10-01");
  });

  it("leaves defaults out of the address", () => {
    const { state } = parseListState(new URLSearchParams(""));
    expect(toSearchParams(state).toString()).toBe("");
    expect(toSearchParams({ ...state, page: 2, pageSize: 50 }).toString()).toBe("page=2&page_size=50");
  });

  it("blocks a mixed-agent selection", () => {
    const mixed = new Map([
      ["call_1", "agt_a"],
      ["call_2", "agt_b"],
    ]);
    expect(checkSimulation(mixed)).toEqual({ ok: false, reason: "Select calls from a single agent to run a simulation" });
    expect(checkSimulation(new Map([["call_1", "agt_a"]]))).toEqual({ ok: true, agentId: "agt_a" });
  });
});

describe("CallHistoryPage (006 US1)", () => {
  it("lists 20 of 45 newest first and pages through", async () => {
    seedMockCalls(45);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/calls");
    await waitFor(() => expect(rowsOnPage()).toHaveLength(20), { timeout: 5000 });
    expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveTextContent("1 to 20 of 45 calls");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveTextContent("21 to 40 of 45 calls"), { timeout: 5000 });
  });

  it("keeps the selection across pages and blocks a mixed-agent simulation", async () => {
    seedMockCalls(45);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/calls");
    await waitFor(() => expect(rowsOnPage()).toHaveLength(20), { timeout: 5000 });
    for (const i of [0, 1, 2]) await user.click(rowsOnPage()[i]!);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveTextContent("21 to 40"), { timeout: 5000 });
    for (const i of [0, 1]) await user.click(rowsOnPage()[i]!);
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() =>
      expect(within(screen.getByRole("table")).getByRole("checkbox", { name: `Select call ${mockCallId(0)}` })).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
    expect(screen.getByText("selected").parentElement).toHaveTextContent("5 selected");
    await user.click(screen.getByRole("button", { name: "Run simulation" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Select calls from a single agent to run a simulation");
  });

  it("shows applied filters as chips and clears them", async () => {
    seedMockCalls(45);
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/calls?status=completed&channel=whatsapp&agent_id=${MOCK_AGENTS[0]!.id}`);
    const group = await screen.findByRole("group", { name: "Applied filters" });
    expect(within(group).getAllByRole("button", { name: /^Remove filter/ })).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Filters, 3 applied" })).toBeInTheDocument();
    await user.click(within(group).getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(screen.queryByRole("group", { name: "Applied filters" })).not.toBeInTheDocument());
  });

  it("says when nothing matches and offers to clear", async () => {
    seedMockCalls(5);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/calls?status=voicemail");
    expect(await screen.findByText("No calls match these filters", undefined, { timeout: 5000 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(rowsOnPage()).toHaveLength(5), { timeout: 5000 });
  });

  it("sends a typed plus sign as %2B", async () => {
    seedMockCalls(45);
    await signInDemo();
    renderApp("/calls?from_number=%2B1555");
    await waitFor(() => expect(mockCalls().requests.some((r) => r.includes("from_number=%2B1555"))).toBe(true), { timeout: 5000 });
    await waitFor(() => expect(rowsOnPage()).toHaveLength(1), { timeout: 5000 });
  });

  it("hides a column and remembers it; required columns stay", async () => {
    seedMockCalls(3);
    await signInDemo();
    const user = userEvent.setup();
    const first = renderApp("/calls");
    await waitFor(() => expect(rowsOnPage()).toHaveLength(3), { timeout: 5000 });
    expect(screen.getByRole("columnheader", { name: "Summary" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Columns" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Summary" }));
    expect(screen.getByRole("menuitemcheckbox", { name: /Call ID/ })).toHaveAttribute("aria-disabled", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("columnheader", { name: "Summary" })).not.toBeInTheDocument();
    first.unmount();
    renderApp("/calls");
    await waitFor(() => expect(rowsOnPage()).toHaveLength(3), { timeout: 5000 });
    expect(screen.queryByRole("columnheader", { name: "Summary" })).not.toBeInTheDocument();
  });

  it("offers 10, 20, 50 and 100 rows per page", async () => {
    seedMockCalls(3);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/calls");
    await user.click(await screen.findByRole("combobox", { name: "Rows per page" }));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["10", "20", "50", "100"]);
  });
});
