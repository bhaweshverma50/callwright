/**
 * The fake payment gateway's checkout pages (STRIPE_MODE=fake, services/api/app/dev/router.py).
 * These dev endpoints are outside the contract, so they go through plain fetch and readJson.
 */
import { useQuery } from "@tanstack/react-query";
import { env } from "../lib/env";
import { readJson } from "./client";
import { networkError } from "./errors";

export interface TestCard {
  number: string;
  brand: string;
  label: string;
  outcome: string;
}

export interface CheckoutSessionInfo {
  id: string;
  amount_usd: string;
  status: "pending" | "completed" | "expired";
  workspace_name: string | null;
  cancel_url: string;
  test_cards: TestCard[];
}

export interface CardPayment {
  card_number: string;
  exp_month: number;
  exp_year: number;
  cvc: string;
  name: string;
}

export const devCheckoutKeys = {
  session: (id: string) => ["dev", "checkout", id] as const,
};

async function devCall<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${env.apiBaseUrl}/dev/fake-checkout/${path}`, { headers: { "content-type": "application/json" }, ...init });
  } catch {
    throw networkError();
  }
  return readJson<T>(res);
}

export function useTestCheckout(sessionId: string) {
  return useQuery({
    queryKey: devCheckoutKeys.session(sessionId),
    queryFn: () => devCall<CheckoutSessionInfo>(encodeURIComponent(sessionId)),
    retry: false,
  });
}

export function payTestCheckout(sessionId: string, card: CardPayment) {
  return devCall<{ redirect_url: string }>(`${encodeURIComponent(sessionId)}/pay`, { method: "POST", body: JSON.stringify(card) });
}

export function cancelTestCheckout(sessionId: string) {
  return devCall<{ redirect_url: string }>(`${encodeURIComponent(sessionId)}/cancel`, { method: "POST" });
}
