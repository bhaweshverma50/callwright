import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { resetMockChannels, seedMockChannels } from "../../mocks/channels/handlers";
import { renderApp, signInDemo } from "../../test/render";

describe("Channels page (T023, T082)", () => {
  beforeEach(async () => {
    resetMockChannels();
    await signInDemo();
  });

  it("uses the same name in the sidebar and the title, and starts with the import call to action", async () => {
    renderApp("/phone-numbers");
    // The first render also loads the lazy page chunk, which is slow on a busy machine.
    expect(await screen.findByRole("heading", { level: 1, name: "Channels" }, { timeout: 10_000 })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Channels/ }).length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "Put an agent on a phone number" })).toBeInTheDocument();
    expect(screen.getByText("sip:sip.callwright.example")).toBeInTheDocument();
  });

  it("lists numbers and opens the detail panel with agents and outbound call", async () => {
    seedMockChannels();
    const user = userEvent.setup();
    renderApp("/phone-numbers");
    const card = await screen.findByRole("button", { name: /Open \+14155550100/ });
    expect(within(card).getByText("No agent: calls declined")).toBeInTheDocument();
    await user.click(card);
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByRole("button", { name: "Make outbound call" })).toBeInTheDocument();
    expect(within(panel).getByText("Saved. Leave empty to keep it.")).toBeInTheDocument();
  });

  it("shows the WhatsApp and compliance tabs", async () => {
    const user = userEvent.setup();
    renderApp("/phone-numbers");
    await user.click(await screen.findByRole("tab", { name: /WhatsApp/ }));
    expect(await screen.findByRole("heading", { name: "Answer WhatsApp calls with an agent" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /Compliance/ }));
    await waitFor(() => expect(screen.getByText("Do-not-call list")).toBeInTheDocument());
    expect(await screen.findByLabelText("Calls on Monday")).toBeInTheDocument();
  });
});
