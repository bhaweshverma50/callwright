import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { seedKb } from "../../../mocks/tools";
import { AgentKnowledgePicker } from "./AgentKnowledgePicker";
import { renderWithProviders } from "../../../test/render";

function renderPicker(attachedIds: string[], onConfirm = vi.fn()) {
  renderWithProviders(<AgentKnowledgePicker open onOpenChange={() => undefined} attachedIds={attachedIds} onConfirm={onConfirm} />, { router: true });
  return onConfirm;
}

describe("AgentKnowledgePicker (005 T080, T099)", () => {
  it("groups ready and not ready bases; not ready ones cannot be picked", async () => {
    seedKb("Clinic policies", [{ name: "refunds.pdf", status: "ready" }]);
    seedKb("Price list", [{ name: "prices.pdf", status: "processing" }]);
    seedKb("Empty");
    renderPicker([]);
    const ready = await screen.findByRole("region", { name: "Ready" });
    expect(within(ready).getByText("Clinic policies")).toBeInTheDocument();
    const notReady = screen.getByRole("region", { name: "Not ready" });
    expect(within(notReady).getByText("Documents are still being processed")).toBeInTheDocument();
    expect(within(notReady).getByText("No documents yet")).toBeInTheDocument();
    for (const box of within(notReady).getAllByRole("checkbox")) expect(box).toBeDisabled();
  });

  it("keeps Confirm disabled until the selection changes", async () => {
    const kb = seedKb("Clinic policies", [{ name: "refunds.pdf", status: "ready" }]);
    const other = seedKb("Insurance", [{ name: "plans.pdf", status: "ready" }]);
    const onConfirm = renderPicker([kb.id]);
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled();
    await userEvent.click(await screen.findByRole("checkbox", { name: /Insurance/ }));
    expect(confirm).toBeEnabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Insurance/ }));
    expect(confirm).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Insurance/ }));
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith([kb.id, other.id]);
  });

  it("filters by search and explains the empty library", async () => {
    seedKb("Clinic policies", [{ name: "refunds.pdf", status: "ready" }]);
    renderPicker([]);
    await screen.findByText("Clinic policies");
    await userEvent.type(screen.getByLabelText("Search knowledge bases"), "zzz");
    expect(screen.getByText('Nothing matches "zzz"')).toBeInTheDocument();
  });

  it("offers create and upload when there is nothing yet", async () => {
    renderPicker([]);
    expect(await screen.findByText("No knowledge bases yet")).toBeInTheDocument();
    expect(screen.getByText(/PDF or Word \(\.docx\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New and upload" })).toBeInTheDocument();
  });
});
