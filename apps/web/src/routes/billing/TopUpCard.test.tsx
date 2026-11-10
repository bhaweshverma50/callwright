import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders, signInDemo } from "../../test/render";
import { env } from "../../lib/env";
import { server } from "../../mocks/node";
import { TopUpCard } from "./TopUpCard";

/** Every checkout session the card asks for, by amount. The answer points at this page, so jsdom stays put. */
function setup() {
  const checkouts: string[] = [];
  server.use(
    http.post(`${env.apiBaseUrl}/billing/checkout-sessions`, async ({ request }) => {
      checkouts.push(((await request.json()) as { amount_usd: string }).amount_usd);
      return HttpResponse.json({ checkout_url: window.location.href, expires_at: new Date(Date.now() + 60_000).toISOString() }, { status: 201 });
    }),
  );
  renderWithProviders(<TopUpCard />);
  return { checkouts, user: userEvent.setup(), amount: screen.getByLabelText("Amount", { selector: "input" }) };
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
    const { user, amount, checkouts } = setup();
    await user.type(amount, value);
    await user.tab();
    await waitFor(() => expect(screen.getAllByRole("alert").map((a) => a.textContent)).toContain(reason));
    expect(addButton()).toBeDisabled();
    expect(amount).toHaveAttribute("aria-invalid", "true");
    expect(checkouts).toEqual([]);
  });

  it("presets only fill the amount; checkout starts from the named button", async () => {
    const { user, amount, checkouts } = setup();
    await user.click(screen.getByRole("button", { name: "$100" }));
    expect(amount).toHaveValue("100.00");
    expect(screen.getByRole("button", { name: "$100" })).toHaveAttribute("aria-pressed", "true");
    expect(checkouts).toEqual([]);

    const add = addButton();
    expect(add).toHaveTextContent("Add funds $100.00");
    await user.click(add);
    await waitFor(() => expect(checkouts).toEqual(["100.00"]));
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
