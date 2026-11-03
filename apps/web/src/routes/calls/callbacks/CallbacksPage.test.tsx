import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockCallbackId, mockCallbacks } from "../../../mocks/callbacks/handlers";
import { mockCallId, seedMockCalls } from "../../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../../test/render";
import { localTimeLabel, zoneLabel } from "./format";

const bodyRows = () => within(screen.getByRole("table")).getAllByRole("row").slice(1);

describe("callback time display (011)", () => {
  it("shows the recipient's wall clock and a short zone name", () => {
    expect(localTimeLabel({ local_time: "2026-11-04T17:00:00", scheduled_at: "2026-11-04T11:30:00Z", timezone: "Asia/Kolkata" })).toBe(
      "Wed 4 Nov, 5:00 pm",
    );
    expect(zoneLabel("Asia/Kolkata", "2026-11-04T11:30:00Z")).toBe("IST");
    expect(zoneLabel("America/New_York", "2026-10-17T21:00:00Z")).toBe("EDT");
    expect(zoneLabel("Europe/London", "2026-10-16T08:00:00Z")).toBe("BST");
  });
});

describe("CallbacksPage (011)", () => {
  it("lists every callback and filters by status", async () => {
    seedMockCalls(45);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/calls/callbacks");
    await waitFor(() => expect(bodyRows()).toHaveLength(8), { timeout: 5000 });
    expect(screen.getByRole("tab", { name: /Callbacks/ })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("radio", { name: "Failed" }));
    await waitFor(() => expect(bodyRows()).toHaveLength(2), { timeout: 5000 });
    expect(within(screen.getByRole("table")).getByText("On the do-not-call list")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Balance too low")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Scheduled" }));
    await waitFor(() => expect(bodyRows()).toHaveLength(3), { timeout: 5000 });
    // Soonest first: Kolkata 10:00 IST (04:30 UTC), then New York 5:00 pm, then Los Angeles 9:30 am the day after.
    expect(bodyRows()[0]).toHaveTextContent("Sat 17 Oct, 10:00 am");
    expect(bodyRows()[2]).toHaveTextContent("Sun 18 Oct, 9:30 am");
  });

  it("cancels a scheduled callback after confirmation", async () => {
    seedMockCalls(45);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/calls/callbacks?status=scheduled");
    await waitFor(() => expect(bodyRows()).toHaveLength(3), { timeout: 5000 });
    await user.click(within(bodyRows()[1]!).getByRole("button", { name: /Cancel the callback to \+1 555 123 4567/ }));
    const confirm = await screen.findByRole("alertdialog", { name: "Cancel this callback?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel callback" }));
    await waitFor(() => expect(mockCallbacks().cancelled).toEqual([mockCallbackId(0)]));
    await waitFor(() => expect(bodyRows()).toHaveLength(2), { timeout: 5000 });
  });

  it("opens the resulting call in the call drawer on the same page", async () => {
    seedMockCalls(45);
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/calls/callbacks?status=placed");
    await waitFor(() => expect(bodyRows()).toHaveLength(1), { timeout: 5000 });
    await user.click(within(bodyRows()[0]!).getByRole("link", { name: "Open the callback call to +1 415 555 0013" }));
    expect(router.state.location.pathname).toBe("/calls/callbacks");
    expect(router.state.location.search).toContain(`call=${mockCallId(9)}`);
    expect(await screen.findByRole("dialog", undefined, { timeout: 5000 })).toBeInTheDocument();
  });

  it("explains where callbacks come from when there are none", async () => {
    await signInDemo();
    renderApp("/calls/callbacks");
    expect(await screen.findByText("No callbacks yet", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/booked by your agents during phone calls/)).toBeInTheDocument();
  });
});
