import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "../../app/queryClient";
import { Toaster, TooltipProvider } from "../../components";
import { seedMockCalls } from "../../mocks/calls/handlers";
import { qualityStore } from "../../mocks/quality/handlers";
import { CustomEvaluatorDialog } from "./CustomEvaluatorDialog";

function renderDialog() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <MemoryRouter>
          <CustomEvaluatorDialog open onOpenChange={() => {}} />
          <Toaster />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("CustomEvaluatorDialog (007 T062, T088, US5)", () => {
  it("picks a template, goes Back, and enables Create only with a name and a phrase", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Required or forbidden phrase" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Custom judge question" }));
    expect(await within(dialog).findByLabelText("Yes or no question")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Back" }));
    await user.click(await within(dialog).findByRole("button", { name: "Required or forbidden phrase" }));
    const create = await within(dialog).findByRole("button", { name: "Create check" });
    expect(create).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Name"), "No guarantees");
    expect(within(dialog).getByTestId("machine-name")).toHaveTextContent("no_guarantees");
    expect(create).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Phrase or pattern"), "guaranteed");
    expect(create).toBeEnabled();
    await user.click(create);
    await waitFor(() => expect(qualityStore().customs.map((c) => c.name)).toEqual(["no_guarantees"]));
    const saved = qualityStore().customs[0]!;
    expect(saved.description).toBeNull();
    expect(saved.config).toMatchObject({ pattern: "guaranteed", mode: "forbidden", target: "agent", is_regex: false });
  });

  it("reports a name already in use on the derived name", async () => {
    const user = userEvent.setup();
    qualityStore().customs.push({
      id: "evl_01MOCKEXISTING00000000000001",
      kind: "custom",
      evaluator_type: "phrase_check",
      name: "no_guarantees",
      display_name: "No guarantees",
      description: null,
      scope: "call",
      cost_class: "free",
      output_kind: "class",
      agent_types: ["single_prompt", "flow"],
      settings_schema: { fields: [] },
      score_range: { min: 0, max: 1 },
      current_version: 1,
      enabled_by_default: false,
      config: { pattern: "x", mode: "forbidden", target: "agent", is_regex: false, case_sensitive: false },
      deleted_at: null,
      versions: [],
    });
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Required or forbidden phrase" }));
    await user.type(await within(dialog).findByLabelText("Name"), "No Guarantees!");
    await user.type(within(dialog).getByLabelText("Phrase or pattern"), "guaranteed");
    await user.click(within(dialog).getByRole("button", { name: "Create check" }));
    expect(await within(dialog).findByText("You already have a custom check named no_guarantees")).toBeInTheDocument();
  });

  it("tries a forbidden pattern on a call and quotes the matching turn", async () => {
    const user = userEvent.setup();
    seedMockCalls(10);
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Required or forbidden phrase" }));
    await user.type(await within(dialog).findByLabelText("Phrase or pattern"), "approval is guaranteed");
    await user.click(within(dialog).getByRole("radio", { name: "Pattern" }));
    await waitFor(() => expect(within(dialog).getByRole("combobox", { name: "Call to try on" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "Try on call" }));
    const result = await within(dialog).findByTestId("trial-result");
    expect(within(result).getByText("Failed")).toBeInTheDocument();
    expect(within(result).getByText(/Turn 4 matched/)).toBeInTheDocument();
  });

  it("refuses a pattern that could run unbounded", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Required or forbidden phrase" }));
    await user.type(await within(dialog).findByLabelText("Name"), "Repeat");
    await user.click(within(dialog).getByRole("radio", { name: "Pattern" }));
    await user.type(within(dialog).getByLabelText("Phrase or pattern"), "(a)\\1");
    await user.click(within(dialog).getByRole("button", { name: "Create check" }));
    expect(await within(dialog).findByText(/cannot use backreferences/)).toBeInTheDocument();
  });
});
