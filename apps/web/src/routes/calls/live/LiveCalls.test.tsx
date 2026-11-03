import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { seedMockCalls, seedMockLiveCalls } from "../../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../../test/render";
import { elapsedSeconds } from "./LiveDuration";
import { liveParty } from "./LiveCalls";

describe("live call helpers", () => {
  it("counts whole seconds from the answer and never goes negative", () => {
    const since = "2026-11-03T10:00:00.000Z";
    expect(elapsedSeconds(since, Date.parse("2026-11-03T10:02:14.900Z"))).toBe(134);
    expect(elapsedSeconds(since, Date.parse("2026-11-03T09:59:00.000Z"))).toBe(0);
    expect(elapsedSeconds(null, Date.now())).toBe(0);
  });

  it("names the outside party the way people say it", () => {
    expect(liveParty({ channel: "sip_inbound", direction: "inbound", from_number: "+14155550142", to_number: "+14155550100" })).toBe(
      "+1 415 555 0142",
    );
    expect(liveParty({ channel: "sip_outbound", direction: "outbound", from_number: "+14155550100", to_number: "+14155550199" })).toBe(
      "+1 415 555 0199",
    );
    expect(liveParty({ channel: "web", direction: "inbound", from_number: null, to_number: null })).toBe("Browser call");
    expect(liveParty({ channel: "sip_inbound", direction: "inbound", from_number: null, to_number: null })).toBe("Unknown caller");
  });
});

describe("Live now (dashboard)", () => {
  it("shows a quiet line when nothing is on air and no badge on Calls", async () => {
    seedMockCalls(6);
    await signInDemo();
    renderApp("/dashboard");
    expect(await screen.findByText("No calls right now.")).toBeInTheDocument();
    expect(screen.queryByTestId("live-calls-badge")).not.toBeInTheDocument();
  });

  it("lists ringing and live calls with a ticking duration, badges Calls and opens the live transcript", async () => {
    seedMockCalls(6);
    seedMockLiveCalls(3);
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/dashboard");
    const card = await screen.findByRole("region", { name: "Live now" });
    const list = await within(card).findByRole("list", { name: "Calls on air" });
    expect(card).toHaveTextContent("3 calls");
    const items = within(list).getAllByRole("button");
    expect(items).toHaveLength(3);
    // The outbound call is still ringing; the inbound phone call has been live for over two minutes.
    const ringing = within(list).getByRole("button", { name: /\+1 415 555 0199, Clinic scheduler is calling/ });
    expect(within(ringing).getByText("Ringing")).toBeInTheDocument();
    const inbound = within(list).getByRole("button", { name: /\+1 415 555 0142, Answered by Order desk/ });
    expect(within(inbound).getByText(/^2:1\d$/)).toBeInTheDocument();
    // Seeded mid-conversation: the latest line heard so far.
    expect(within(inbound).getByText("Sure, it's A as in apple, one two four nine.")).toBeInTheDocument();
    expect(within(list).getByText("Test")).toBeInTheDocument();

    const badge = await screen.findAllByTestId("live-calls-badge");
    expect(badge[0]).toHaveTextContent("3 calls on air");

    await user.click(inbound);
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("On air")).toBeInTheDocument();
    await waitFor(() => expect(within(drawer).getByText(/Thanks for calling, this is the order desk/)).toBeInTheDocument());
  });
});

describe("Call History", () => {
  it("pins calls on air above the table and marks their rows", async () => {
    seedMockCalls(6);
    seedMockLiveCalls(2);
    await signInDemo();
    renderApp("/calls");
    const pinned = await screen.findByRole("list", { name: "Calls on air" });
    expect(within(pinned).getAllByRole("button")).toHaveLength(2);
    const table = await screen.findByRole("table");
    await waitFor(() => expect(within(table).getAllByText("On air").length).toBeGreaterThanOrEqual(2));
  });
});
