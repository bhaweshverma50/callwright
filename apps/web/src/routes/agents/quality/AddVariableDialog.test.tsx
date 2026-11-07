import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "../../../api/queryClient";
import { Toaster, TooltipProvider } from "../../../components";
import { MOCK_AGENTS } from "../../../mocks/calls/handlers";
import { qualityStore } from "../../../mocks/quality/handlers";
import { AddVariableDialog } from "./AddVariableDialog";

const AGENT = MOCK_AGENTS[0]!.id;

function renderDialog() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <MemoryRouter>
          <AddVariableDialog agentId={AGENT} open onOpenChange={() => {}} />
          <Toaster />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("AddVariableDialog (007 T090, US1 scenarios 7 and 8)", () => {
  it('shows and saves "Customer Mood" as customer_mood', async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Customer Mood");
    expect(within(dialog).getByTestId("variable-name")).toHaveTextContent("customer_mood");
    const save = within(dialog).getByRole("button", { name: "Save variable" });
    expect(save).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Description"), "How the caller felt at the end.");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() => expect(qualityStore().variables.some((v) => v.agent_id === AGENT && v.name === "customer_mood")).toBe(true));
    const row = qualityStore().variables.find((v) => v.name === "customer_mood")!;
    expect(row.type).toBe("boolean");
    expect(row.choices).toBeNull();
  });

  it("keeps Save disabled with the naming rule for a name that cannot be normalised", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "!!!");
    await user.type(within(dialog).getByLabelText("Description"), "Something");
    expect(within(dialog).getByText("Use lowercase letters, digits and underscores, starting with a letter")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Save variable" })).toBeDisabled();
  });

  it("hides choices for yes/no, text and number, and needs 2 choices for the fixed set", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Preferred day");
    await user.type(within(dialog).getByLabelText("Description"), "The weekday asked for.");
    for (const type of ["Yes or no", "Text", "Number"]) {
      await user.click(within(dialog).getByRole("radio", { name: type }));
      expect(within(dialog).queryByLabelText("Choices")).not.toBeInTheDocument();
    }
    await user.click(within(dialog).getByRole("radio", { name: "One of a set" }));
    const input = await within(dialog).findByLabelText("Choices");
    const save = within(dialog).getByRole("button", { name: "Save variable" });
    await user.type(input, "Monday{Enter}");
    expect(save).toBeDisabled();
    await user.type(input, "Tuesday{Enter}");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() =>
      expect(qualityStore().variables.find((v) => v.name === "preferred_day" && v.agent_id === AGENT)?.choices).toEqual(["Monday", "Tuesday"]),
    );
  });

  it("shows a name conflict from the server on the name field", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Order found");
    await user.type(within(dialog).getByLabelText("Description"), "Duplicate");
    await user.click(within(dialog).getByRole("button", { name: "Save variable" }));
    expect(await within(dialog).findByText("This agent already has a variable named order_found.")).toBeInTheDocument();
  });
});
