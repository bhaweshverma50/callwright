import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "../../api/queryClient";
import { TooltipProvider } from "../../components";
import { signInDemo } from "../../test/render";
import { TopUpCard, checkoutNavigator } from "./TopUpCard";

function setup() {
  const go = vi.spyOn(checkoutNavigator, "go").mockImplementation(() => {});
  render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <TopUpCard />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { go, user: userEvent.setup(), amount: screen.getByLabelText("Amount", { selector: "input" }) };
}

const addButton = () => screen.getByRole("button", { name: /add funds/i });

describe("TopUpCard (T101, US2.5, US2.6)", () => {
  beforeEach(async () => {
    await signInDemo();
  });

  it.each([
    ["4", "The minimum top-up is $5."],
    ["0", "The minimum top-up is $5."],
    ["10001", "The maximum top-up is $10,000. Contact sales for larger amounts."],
    ["5.555", "Use whole cents: at most two digits after the point."],
  ])("explains why %s is refused and starts no checkout", async (value, reason) => {
    const { user, amount, go } = setup();
    await user.type(amount, value);
    await user.tab();
    await waitFor(() => expect(screen.getAllByRole("alert").map((a) => a.textContent)).toContain(reason));
    expect(addButton()).toBeDisabled();
    expect(amount).toHaveAttribute("aria-invalid", "true");
    expect(go).not.toHaveBeenCalled();
  });

  it("presets only fill the amount; checkout starts from the named button", async () => {
    const { user, amount, go } = setup();
    await user.click(screen.getByRole("button", { name: "$100" }));
    expect(amount).toHaveValue("100.00");
    expect(screen.getByRole("button", { name: "$100" })).toHaveAttribute("aria-pressed", "true");
    expect(go).not.toHaveBeenCalled();

    const add = addButton();
    expect(add).toHaveTextContent("Add funds $100.00");
    await user.click(add);
    await waitFor(() => expect(go).toHaveBeenCalledTimes(1));
    expect(go.mock.calls[0]![0]).toMatch(/\/checkout\/cs_test_fake_mock\w+$/);
  });

  it("accepts the $5 minimum and the $10,000 maximum", async () => {
    const { user, amount } = setup();
    await user.type(amount, "5");
    expect(addButton()).toBeEnabled();
    expect(addButton()).toHaveTextContent("Add funds $5.00");
    await user.clear(amount);
    await user.type(amount, "10,000");
    expect(addButton()).toHaveTextContent("Add funds $10,000.00");
  });
});
