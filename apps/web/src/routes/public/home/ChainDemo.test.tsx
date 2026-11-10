import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ChainDemo } from "./ChainDemo";
import { renderWithProviders } from "../../../test/render";

describe("home chain demo", () => {
  it("plays the turn through the link the visitor picks", async () => {
    renderWithProviders(<ChainDemo />);
    expect(screen.getByRole("tab", { name: /Speech to text/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.setup().click(screen.getByRole("tab", { name: /Language model/ }));
    expect(screen.getByRole("tab", { name: /Language model/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("check_availability")).toBeInTheDocument();
  });
});
