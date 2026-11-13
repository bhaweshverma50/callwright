import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { session } from "../api/session";
import { db } from "../mocks/db";
import { renderApp, signInDemo } from "../test/render";

const SCHEDULED = "2026-12-13T09:00:00.000Z";

describe("Account scheduled for deletion", () => {
  it("shows a full-page state with the date instead of the app", async () => {
    await signInDemo();
    db().users[0]!.deletion_scheduled_at = SCHEDULED;
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: /Your account is scheduled for deletion on/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep my account" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByText(/is forfeited and cannot be refunded/)).toBeInTheDocument();
    // None of the app is there.
    expect(screen.queryByRole("link", { name: "Billing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("Keep my account cancels the deletion and opens the app with a confirmation", async () => {
    await signInDemo();
    db().users[0]!.deletion_scheduled_at = SCHEDULED;
    const user = userEvent.setup();
    renderApp("/settings");
    await user.click(await screen.findByRole("button", { name: "Keep my account" }));
    expect(await screen.findByText("Account kept")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(db().users[0]!.deletion_scheduled_at).toBeUndefined();
  });

  it("Sign out ends the session", async () => {
    await signInDemo();
    db().users[0]!.deletion_scheduled_at = SCHEDULED;
    const user = userEvent.setup();
    const { router } = renderApp("/dashboard");
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in to Callwright" });
    expect(session.isSignedIn()).toBe(false);
    expect(router.state.location.pathname).toBe("/login");
  });
});
