import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp, signInDemo } from "../test/render";
import { session } from "./session";

describe("auth guard (T040, US1.3)", () => {
  it("sends signed-out visitors to sign-in with a return path, then back", async () => {
    const { router } = renderApp("/billing?tab=usage");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent("/billing?tab=usage")}`);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Work email"), "ops@halcyon-dental.com");
    await user.type(screen.getByLabelText("Password", { exact: true }), "correct-horse-9");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/billing"));
    expect(router.state.location.search).toBe("?tab=usage");
  });

  it("shows a plain message for a wrong password", async () => {
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Work email"), "ops@halcyon-dental.com");
    await user.type(screen.getByLabelText("Password", { exact: true }), "not-the-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("That email and password do not match an account.")).toBeInTheDocument();
  });

  it("redirects to sign-in when the session is cleared in another tab", async () => {
    await signInDemo();
    const { router } = renderApp("/settings");
    await screen.findByRole("heading", { name: "Settings" });
    session.clear();
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent("/settings")}`);
  });
});

describe("shell (T042, T095, T096, FR-005, FR-018)", () => {
  it("shows balance to three decimals as a link to billing, and 11 areas", async () => {
    await signInDemo();
    renderApp("/dashboard");
    const chip = await screen.findByRole("link", { name: /^Balance .* Open billing$/ });
    expect(chip).toHaveAttribute("href", "/billing");
    await waitFor(() => expect(chip).toHaveTextContent(/\$\d[\d,]*\.\d{3}$/));
    const nav = screen.getByRole("navigation", { name: "Main" });
    const areas = ["Dashboard", "Agents", "Calls", "Channels", "Knowledge", "Datasets", "Simulations", "Review", "Calibration", "Issues", "Billing"];
    for (const a of areas) expect(within(nav).getByRole("link", { name: a })).toBeInTheDocument();
  });

  it("groups areas in a labelled sidebar and remembers the collapsed state", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const first = renderApp("/dashboard");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const g of ["Build", "Observe", "Quality", "Feedback loop"]) expect(within(nav).getByText(g)).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Workspace" })).getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );

    await user.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(localStorage.getItem("cw.rail.expanded")).toBe("0");
    expect(within(screen.getByRole("navigation", { name: "Main" })).queryByText("Quality")).not.toBeInTheDocument();
    first.unmount();
    renderApp("/dashboard");
    expect(await screen.findByRole("button", { name: "Expand navigation" })).toBeInTheDocument();
  });

  it("shows the numbered setup sequence on an empty dashboard", async () => {
    await signInDemo();
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: "Get your first call on the line" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Setup progress" })).toHaveAttribute("aria-valuenow", "0");
    for (const s of ["Create an agent", "Make a test call", "Connect a number"]) expect(screen.getByRole("heading", { name: s })).toBeInTheDocument();
  });

  it("shows not found inside the shell for unknown addresses", async () => {
    await signInDemo();
    renderApp("/no-such-page");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to dashboard" })).toHaveAttribute("href", "/dashboard");
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("names the record kind for a malformed record id, with no status code", async () => {
    await signInDemo();
    renderApp("/agents/agt_bad");
    expect(await screen.findByRole("heading", { name: "Agent not found" })).toBeInTheDocument();
    expect(screen.queryByText(/404/)).not.toBeInTheDocument();
  });

  it("opens Settings and signs out from the user menu", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: /Account menu for ops@halcyon-dental.com/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Settings" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/settings"));
    await user.click(screen.getByRole("button", { name: /Account menu/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(session.isSignedIn()).toBe(false);
  });
});
