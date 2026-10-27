import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { env } from "../../lib/env";
import { server } from "../../mocks/node";
import { renderApp } from "../../test/render";

const base = `${env.apiBaseUrl}/dev/fake-checkout/cs_test_1`;
const session = {
  id: "cs_test_1",
  amount_usd: "25.00",
  status: "pending",
  workspace_name: "Halcyon Dental Group",
  success_url: "http://localhost/billing?checkout=success",
  cancel_url: "http://localhost/billing?checkout=canceled",
  test_cards: [
    { number: "4242424242424242", brand: "visa", label: "Payment succeeds", outcome: "succeeded" },
    { number: "4000000000009995", brand: "visa", label: "Insufficient funds", outcome: "insufficient_funds" },
  ],
};

describe("test checkout", () => {
  it("shows a decline inline, then pays with a good card", async () => {
    const pays: string[] = [];
    server.use(
      http.get(base, () => HttpResponse.json(session)),
      http.post(`${base}/pay`, async ({ request }) => {
        const { card_number } = (await request.json()) as { card_number: string };
        pays.push(card_number);
        if (card_number !== "4242424242424242")
          return HttpResponse.json(
            { status: 402, title: "Payment declined", code: "insufficient_funds", detail: "Your card has insufficient funds." },
            { status: 402 },
          );
        return HttpResponse.json({ status: "paid", redirect_url: "http://localhost/billing?checkout=success" });
      }),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp("/checkout/cs_test_1");
    expect(await screen.findByText("Add funds to Halcyon Dental Group")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Pay \$25\.00/ }));
    expect(await screen.findByText("Your card number is incomplete.")).toBeInTheDocument();
    expect(pays).toEqual([]);

    await user.click(screen.getByRole("button", { name: /9995, Insufficient funds/ }));
    await user.click(screen.getByRole("button", { name: /Pay \$25\.00/ }));
    expect(await screen.findByText("Your card has insufficient funds.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /4242, Payment succeeds/ }));
    await user.click(screen.getByRole("button", { name: /Pay \$25\.00/ }));
    expect(await screen.findByText("Payment received")).toBeInTheDocument();
    expect(pays).toEqual(["4000000000009995", "4242424242424242"]);
    vi.useRealTimers();
  });

  it("says when the link is not a checkout", async () => {
    server.use(http.get(base, () => HttpResponse.json({ status: 404, code: "not_found" }, { status: 404 })));
    renderApp("/checkout/cs_test_1");
    expect(await screen.findByText("This checkout link isn't valid")).toBeInTheDocument();
  });
});
