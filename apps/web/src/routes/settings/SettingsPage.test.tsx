import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/db";
import { renderApp, signInDemo } from "../../test/render";

describe("SettingsPage (T093, FR-017)", () => {
  it("saves name and recording default together, with a confirmation", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/settings");
    const name = await screen.findByLabelText("Workspace name");
    expect(screen.getByText((_, el) => el?.tagName === "DD" && el.textContent === "5 at once")).toBeInTheDocument();
    expect(screen.getByText("ops@halcyon-dental.com", { selector: "dd" })).toBeInTheDocument();

    await user.clear(name);
    await user.type(name, "Halcyon Front Office");
    await user.click(screen.getByRole("switch", { name: "Record calls by default" }));
    expect(db().workspaces[0]!.name).toBe("Halcyon Dental Group");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Settings saved")).toBeInTheDocument();
    expect(db().workspaces[0]!.name).toBe("Halcyon Front Office");
    expect(db().workspaces[0]!.recording_default).toBe(false);
  });

  it("refuses an empty name inline and saves nothing", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/settings");
    const name = await screen.findByLabelText("Workspace name");
    await user.clear(name);
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Enter a workspace name.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(db().workspaces[0]!.name).toBe("Halcyon Dental Group");
  });

  it("asks before leaving with unsaved changes (FR-021)", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/settings");
    const name = await screen.findByLabelText("Workspace name");
    await user.type(name, " East");
    await user.click(screen.getByRole("link", { name: "Billing" }));
    expect(await screen.findByRole("alertdialog", { name: "Leave without saving?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stay" }));
    expect(router.state.location.pathname).toBe("/settings");
    expect(name).toHaveValue("Halcyon Dental Group East");

    await user.click(screen.getByRole("link", { name: "Billing" }));
    await user.click(await screen.findByRole("button", { name: "Leave" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/billing"));
  });
});
