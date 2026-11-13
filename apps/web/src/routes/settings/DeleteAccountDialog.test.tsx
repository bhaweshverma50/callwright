import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { session } from "../../api/session";
import { DEMO_EMAIL, DEMO_PASSWORD } from "../../mocks/demoAccount";
import { db } from "../../mocks/db";
import { renderApp, signInDemo } from "../../test/render";

async function openDeleteDialog(googleOnly = false) {
  await signInDemo();
  if (googleOnly) db().users[0]!.google_only = true;
  const user = userEvent.setup();
  const app = renderApp("/settings");
  await user.click(await screen.findByRole("button", { name: "Delete account" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Delete your account?" });
  return { user, dialog, ...app };
}

describe("Delete account", () => {
  it("lists what is erased, the exact balance forfeited and the date", async () => {
    const { dialog } = await openDeleteDialog();
    expect(within(dialog).getByText("Agents and all their versions")).toBeInTheDocument();
    expect(within(dialog).getByText(/Phone numbers and WhatsApp channels are released/)).toBeInTheDocument();
    const balance = db().transactions.length ? screen.getAllByText(/^\$\d[\d,]*\.\d{3}$/)[0]!.textContent : "";
    expect(balance).toMatch(/^\$/);
    expect(within(dialog).getByText(/is forfeited\. It cannot be refunded\./)).toBeInTheDocument();
    expect(within(dialog).getByText(/Nothing is erased for 30 days\. On /)).toBeInTheDocument();
  });

  it("keeps Delete off until the name, the forfeit box and the password are all given", async () => {
    const { user, dialog } = await openDeleteDialog();
    const del = within(dialog).getByRole("button", { name: "Delete account" });
    expect(del).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Type the workspace name to confirm"), "Halcyon Dental");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.type(within(dialog).getByLabelText("Your password"), DEMO_PASSWORD);
    expect(del).toBeDisabled(); // the name is not complete

    await user.type(within(dialog).getByLabelText("Type the workspace name to confirm"), " Group");
    expect(del).toBeEnabled();

    await user.click(within(dialog).getByRole("checkbox"));
    expect(del).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox"));
    expect(del).toBeEnabled();

    await user.clear(within(dialog).getByLabelText("Your password"));
    expect(del).toBeDisabled();
  });

  it("matches the workspace name exactly", async () => {
    const { user, dialog } = await openDeleteDialog();
    await user.type(within(dialog).getByLabelText("Type the workspace name to confirm"), "halcyon dental group");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.type(within(dialog).getByLabelText("Your password"), DEMO_PASSWORD);
    expect(within(dialog).getByRole("button", { name: "Delete account" })).toBeDisabled();
  });

  it("asks an account created with Google to type its email instead of a password", async () => {
    const { user, dialog } = await openDeleteDialog(true);
    expect(within(dialog).queryByLabelText("Your password")).not.toBeInTheDocument();
    const del = within(dialog).getByRole("button", { name: "Delete account" });
    await user.type(within(dialog).getByLabelText("Type the workspace name to confirm"), "Halcyon Dental Group");
    await user.click(within(dialog).getByRole("checkbox"));
    expect(del).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type your email to confirm"), "someone@else.com");
    expect(del).toBeDisabled();
    await user.clear(within(dialog).getByLabelText("Type your email to confirm"));
    await user.type(within(dialog).getByLabelText("Type your email to confirm"), DEMO_EMAIL);
    expect(del).toBeEnabled();
  });

  it("says when the password is wrong and schedules nothing", async () => {
    const { user, dialog } = await openDeleteDialog();
    await user.type(within(dialog).getByLabelText("Type the workspace name to confirm"), "Halcyon Dental Group");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.type(within(dialog).getByLabelText("Your password"), "not-my-password");
    await user.click(within(dialog).getByRole("button", { name: "Delete account" }));
    expect(await within(dialog).findByText("That password is not correct.")).toBeInTheDocument();
    expect(db().users[0]!.deletion_scheduled_at).toBeUndefined();
    expect(session.isSignedIn()).toBe(true);
  });

  it("schedules the deletion, signs out and shows the sign-in page with a notice", async () => {
    const { user, dialog, router } = await openDeleteDialog();
    await user.type(within(dialog).getByLabelText("Type the workspace name to confirm"), "Halcyon Dental Group");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.type(within(dialog).getByLabelText("Your password"), DEMO_PASSWORD);
    await user.click(within(dialog).getByRole("button", { name: "Delete account" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(await screen.findByText(/Your account is scheduled for deletion on/)).toBeInTheDocument();
    expect(screen.getByText(/choose Keep my account to cancel/)).toBeInTheDocument();
    expect(session.isSignedIn()).toBe(false);
    expect(db().users[0]!.deletion_scheduled_at).toBeDefined();
  });
});
