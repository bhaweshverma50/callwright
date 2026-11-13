import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { session } from "../../api/session";
import { DEMO_EMAIL, DEMO_PASSWORD } from "../../mocks/demoAccount";
import { db } from "../../mocks/db";
import { renderApp, signInDemo } from "../../test/render";

const NEW_PASSWORD = "a-brand-new-pass-7";

async function openChangePassword() {
  await signInDemo();
  const user = userEvent.setup();
  renderApp("/settings");
  await user.click(await screen.findByRole("button", { name: "Change password" }));
  const dialog = await screen.findByRole("dialog", { name: "Change password" });
  return { user, dialog };
}

describe("Account panel on Settings", () => {
  it("shows the email and the password action", async () => {
    await signInDemo();
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Account" })).toBeInTheDocument();
    expect(screen.getByText(DEMO_EMAIL, { selector: "dd > span" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set a password" })).not.toBeInTheDocument();
  });

  it("offers Set a password instead of the change form to an account created with Google", async () => {
    await signInDemo();
    db().users[0]!.google_only = true;
    const user = userEvent.setup();
    renderApp("/settings");
    expect(screen.queryByRole("button", { name: "Change password" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Set a password" }));
    expect(await screen.findByText("Check your email")).toBeInTheDocument();
    expect(db().resetTokens[`reset-${DEMO_EMAIL}`]).toBeDefined();
  });
});

describe("Change password dialog", () => {
  it("checks every field before it asks the server", async () => {
    const { user, dialog } = await openChangePassword();
    const submit = within(dialog).getByRole("button", { name: "Change password" });
    await user.click(submit);
    expect(await within(dialog).findByText("Enter your current password.")).toBeInTheDocument();
    expect(within(dialog).getByText("Use at least 10 characters.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Current password"), DEMO_PASSWORD);
    await user.type(within(dialog).getByLabelText("New password"), DEMO_PASSWORD);
    await user.type(within(dialog).getByLabelText("Repeat the new password"), "something-else-1");
    await user.click(submit);
    expect(await within(dialog).findByText("Choose a password different from your current one.")).toBeInTheDocument();
    expect(within(dialog).getByText("The two passwords do not match.")).toBeInTheDocument();
    expect(db().users[0]!.password).toBe(DEMO_PASSWORD);
  });

  it("reveals and hides what is typed", async () => {
    const { user, dialog } = await openChangePassword();
    const field = within(dialog).getByLabelText("New password");
    expect(field).toHaveAttribute("type", "password");
    await user.click(within(dialog).getByRole("button", { name: "Show new password" }));
    expect(field).toHaveAttribute("type", "text");
    await user.click(within(dialog).getByRole("button", { name: "Hide new password" }));
    expect(field).toHaveAttribute("type", "password");
  });

  it("says when the current password is wrong", async () => {
    const { user, dialog } = await openChangePassword();
    await user.type(within(dialog).getByLabelText("Current password"), "not-my-password");
    await user.type(within(dialog).getByLabelText("New password"), NEW_PASSWORD);
    await user.type(within(dialog).getByLabelText("Repeat the new password"), NEW_PASSWORD);
    await user.click(within(dialog).getByRole("button", { name: "Change password" }));
    expect(await within(dialog).findByText("Your current password is not correct.")).toBeInTheDocument();
    expect(db().users[0]!.password).toBe(DEMO_PASSWORD);
    expect(session.isSignedIn()).toBe(true);
    // One wrong attempt is one failure: the client did not refresh its session and send it again.
    expect(db().failures[DEMO_EMAIL]?.count).toBe(1);
  });

  it("changes the password, keeps this device signed in and confirms", async () => {
    const { user, dialog } = await openChangePassword();
    const before = session.accessToken();
    await user.type(within(dialog).getByLabelText("Current password"), DEMO_PASSWORD);
    await user.type(within(dialog).getByLabelText("New password"), NEW_PASSWORD);
    await user.type(within(dialog).getByLabelText("Repeat the new password"), NEW_PASSWORD);
    await user.click(within(dialog).getByRole("button", { name: "Change password" }));

    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(screen.getByText("Your other devices were signed out.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Change password" })).not.toBeInTheDocument());
    expect(db().users[0]!.password).toBe(NEW_PASSWORD);
    expect(session.accessToken()).not.toBe(before);
    expect(session.isSignedIn()).toBe(true);
  });
});
