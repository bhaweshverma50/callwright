import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ChainDemo } from "./ChainDemo";
import { createQueryClient } from "../../../api/queryClient";

describe("home chain demo", () => {
  it("plays the turn through the link the visitor picks", async () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <ChainDemo />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("tab", { name: /Speech to text/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.setup().click(screen.getByRole("tab", { name: /Language model/ }));
    expect(screen.getByRole("tab", { name: /Language model/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("check_availability")).toBeInTheDocument();
  });
});
