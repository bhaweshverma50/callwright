import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { seedMockCalls } from "../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../test/render";
import { EMPTY_QUEUE, verdictLine } from "./ReviewPage";

// The drawer is modal, so the page behind it is hidden from the accessibility tree while it is open.
const tab = (name: RegExp) => screen.findByRole("tab", { name, hidden: true }, { timeout: 5000 });

describe("verdictLine (007 FR-025)", () => {
  it.each([
    [5, 0, "all 5 passed"],
    [3, 2, "2 failed · 3 passed"],
    [0, 3, "all 3 failed"],
    [0, 0, "no checks run yet"],
  ])("%i passed and %i failed reads %s", (pass, fail, text) => {
    expect(verdictLine({ pass_count: pass, fail_count: fail })).toBe(text);
  });
});

describe("ReviewPage (007 T067, US6)", () => {
  it("opens on Mixed verdicts with counts, closest split first", async () => {
    seedMockCalls(45);
    await signInDemo();
    renderApp("/review");
    const mixed = await tab(/Mixed verdicts/);
    expect(mixed).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(within(mixed).getByLabelText("5 calls")).toBeInTheDocument());
    expect(within(await tab(/Flagged/)).getByLabelText("6 calls")).toBeInTheDocument();
    expect(within(await tab(/Random/)).getByLabelText("10 calls")).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Mixed verdicts queue" }, { timeout: 5000 });
    const cards = within(list).getAllByRole("button");
    expect(cards).toHaveLength(5);
    expect(cards[0]).toHaveAccessibleName(/3 failed · 3 passed/);
  });

  it("labels a call from the drawer, offers the next call and drops the counts", async () => {
    const user = userEvent.setup();
    seedMockCalls(45);
    await signInDemo();
    renderApp("/review");
    const list = await screen.findByRole("list", { name: "Mixed verdicts queue" }, { timeout: 5000 });
    await user.click(within(list).getAllByRole("button")[0]!);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    const group = await within(drawer).findByRole("group", { name: "Your label" }, { timeout: 5000 });
    await user.click(within(group).getByRole("button", { name: "Good" }));
    expect(await within(drawer).findByText("Labelled. It leaves the queue.")).toBeInTheDocument();
    await waitFor(async () => expect(within(await tab(/Mixed verdicts/)).getByLabelText("4 calls")).toBeInTheDocument());
    expect(within(await tab(/Flagged/)).getByLabelText("5 calls")).toBeInTheDocument();
    expect(within(await tab(/Random/)).getByLabelText("9 calls")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "Next call" }));
    await waitFor(() => expect(within(group).queryByRole("button", { name: "Good", pressed: true })).not.toBeInTheDocument());
  });

  it("explains an empty queue", async () => {
    await signInDemo();
    renderApp("/review");
    expect(await screen.findByText(EMPTY_QUEUE, undefined, { timeout: 5000 })).toBeInTheDocument();
  });
});
