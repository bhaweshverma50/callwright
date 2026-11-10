import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { api, unwrap } from "../../api/client";
import { server } from "../../mocks/node";
import { renderApp, signInDemo } from "../../test/render";
import { session } from "../../api/session";
import { DEMO_PASSWORD, mockVerifyToken } from "../../mocks/demoAccount";

/** A brand-new verified account: a workspace with no agents and no saved tour progress. */
async function signUpFresh() {
  const email = `new.${Math.random().toString(36).slice(2, 10)}@example.com`;
  await unwrap(api.POST("/auth/register", { body: { email, password: DEMO_PASSWORD } }));
  session.set(await unwrap(api.POST("/auth/verify-email", { body: { token_hash: mockVerifyToken(email) } })));
}

/** Every PATCH /me/preferences body, in order. */
let saves: unknown[] = [];
beforeEach(() => {
  saves = [];
  server.events.on("request:start", ({ request }) => {
    if (request.method === "PATCH" && new URL(request.url).pathname.endsWith("/me/preferences"))
      void request
        .clone()
        .json()
        .then((b: { onboarding: unknown }) => saves.push(b.onboarding));
  });
});
afterEach(() => server.events.removeAllListeners());

const tourTitle = () => document.getElementById("tour-title");
// Steps wait for lazy pages and their data before the popover shows.
const slow = { timeout: 4000 };

describe("guided setup tour (013)", () => {
  it("welcomes a new user once, starts on Start tour and saves the step", async () => {
    await signUpFresh();
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    const welcome = await screen.findByRole("dialog", { name: "Set up your first agent" });
    await user.click(within(welcome).getByRole("button", { name: "Start tour" }));

    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents"));
    await waitFor(() => expect(saves).toContainEqual({ status: "in_progress", step: "agents" }));
    expect(screen.getByText(/Step 1 of 10/)).toBeInTheDocument();
  });

  it("moves on when the user does the real action", { timeout: 15_000 }, async () => {
    await signUpFresh();
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: "Start tour" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
    expect(screen.getByText(/Open the templates to go on/)).toBeInTheDocument();

    // The page's own link, not a tour button.
    await user.click(await screen.findByRole("link", { name: "Start from a template" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/templates"));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Pick a template"), slow);
    await waitFor(() => expect(saves).toContainEqual({ status: "in_progress", step: "template" }));
  });

  it("creates an agent from a template on Do it for me and follows it into the editor", { timeout: 15_000 }, async () => {
    await signUpFresh();
    const user = userEvent.setup();
    const { router } = renderApp("/agents/templates");
    await user.click(await screen.findByRole("button", { name: "Start tour" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Pick a template"), slow);
    await user.click(await screen.findByRole("button", { name: "Choose one for me" }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/agents\/agt_[0-9A-Z]{26}\/edit$/), slow);
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Tell it what to do"), slow);
  });

  it("skip for now records skipped and never shows the welcome again", async () => {
    await signUpFresh();
    const user = userEvent.setup();
    const first = renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(saves).toContainEqual({ status: "skipped", step: "agents" }));
    expect(screen.queryByRole("dialog", { name: "Set up your first agent" })).not.toBeInTheDocument();
    first.unmount();

    renderApp("/dashboard");
    await screen.findByRole("heading", { name: "Dashboard" });
    // The welcome card would open once the saved preference loads; fail if it does.
    await expect(screen.findByRole("dialog", { name: "Set up your first agent" }, { timeout: 1000 })).rejects.toThrow();
  });

  it("skip tour ends it from any step", { timeout: 15_000 }, async () => {
    await signUpFresh();
    const user = userEvent.setup();
    renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: "Start tour" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Pick a template"), slow);
    await user.click(screen.getByRole("button", { name: "Skip tour" }));
    await waitFor(() => expect(tourTitle()).toBeNull());
    await waitFor(() => expect(saves.at(-1)).toEqual({ status: "skipped", step: "template" }));
  });

  it("does not auto-start for an existing user, who can start it from the account menu", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: /Account menu for/ }));
    expect(screen.queryByRole("dialog", { name: "Set up your first agent" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("menuitem", { name: "Guided setup" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/agents"));
    await waitFor(() => expect(saves).toContainEqual({ status: "in_progress", step: "agents" }));
  });

  it("pauses on Esc and resumes at the same step", async () => {
    await signUpFresh();
    const user = userEvent.setup();
    renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: "Start tour" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
    await waitFor(() => expect(tourTitle()).toHaveFocus());
    await user.keyboard("{Escape}");
    const chip = await screen.findByRole("region", { name: "Guided setup paused" });
    expect(chip).toHaveTextContent("Step 1 of 10: Start with an agent");
    expect(tourTitle()).toBeNull();
    await user.click(within(chip).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Start with an agent"));
  });

  it("resumes saved progress after a reload, at the saved step", async () => {
    await signInDemo();
    await unwrap(api.PATCH("/me/preferences", { body: { onboarding: { status: "in_progress", step: "channels" } } }));
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    const chip = await screen.findByRole("region", { name: "Guided setup paused" });
    expect(chip).toHaveTextContent("Step 8 of 10: Put it on a number");
    await user.click(within(chip).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/phone-numbers"));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Put it on a number"));
    // Arrow keys move between steps from inside the popover.
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Find every call"));
    await waitFor(() => expect(saves.at(-1)).toEqual({ status: "in_progress", step: "calls" }));
  });

  it("finishes from the recap and saves completed", async () => {
    await signInDemo();
    await unwrap(api.PATCH("/me/preferences", { body: { onboarding: { status: "in_progress", step: "quality" } } }));
    const user = userEvent.setup();
    renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Check the quality"));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(tourTitle()).toHaveTextContent("Your agent is set up"));
    await user.click(screen.getByRole("button", { name: "Finish" }));
    await waitFor(() => expect(saves.at(-1)).toEqual({ status: "completed", step: "done" }));
    expect(tourTitle()).toBeNull();
  });
});
