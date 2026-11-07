import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DiffView } from "./DiffView";
import { lineDiff } from "../../../lib/lineDiff";

// 002 T085: the folded run of unchanged lines is a row of the table, so the table holds only rows.
describe("DiffView structure", () => {
  it("puts the fold button in a row and cell, and expands it", async () => {
    const before = Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n");
    const after = before.replace("line 11", "line eleven");
    render(<DiffView lines={lineDiff(before, after)} />);
    const table = screen.getByRole("table", { name: "Line changes" });
    for (const child of Array.from(table.children)) expect(child).toHaveAttribute("role", "row");
    const fold = within(table).getByRole("button", { name: /unchanged lines/ });
    expect(fold.closest("[role=cell]")).not.toBeNull();
    await userEvent.setup().click(fold);
    expect(within(table).queryByRole("button", { name: /unchanged lines/ })).toBeNull();
    expect(within(table).getByText("line 0")).toBeInTheDocument();
  });
});
