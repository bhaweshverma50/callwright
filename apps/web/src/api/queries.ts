/** TanStack Query hooks for the 001 endpoints. Query keys are shared so the balance chip and
 * the billing page update together (R12). */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { QuoteRequest, TransactionType } from "./types";
import { session } from "./session";

export const qk = {
  me: ["me"] as const,
  balance: ["billing", "balance"] as const,
  transactions: (page: number, pageSize: number, type?: TransactionType) =>
    ["billing", "transactions", { page, pageSize, type: type ?? null }] as const,
  transactionsAll: ["billing", "transactions"] as const,
  usage: (from: string, to: string) => ["usage", { from, to }] as const,
  catalog: ["pricing", "catalog"] as const,
  quote: (req: QuoteRequest) => ["pricing", "quote", req] as const,
};

export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: () => unwrap(api.GET("/me")),
    enabled: session.isSignedIn(),
    staleTime: 30_000,
  });
}

export function useBalance(opts: { pollMs?: number | false } = {}) {
  return useQuery({
    queryKey: qk.balance,
    queryFn: () => unwrap(api.GET("/billing/balance")),
    enabled: session.isSignedIn(),
    refetchOnWindowFocus: true,
    refetchInterval: opts.pollMs ?? 60_000,
  });
}

export function useTransactions(page: number, pageSize: number, type?: TransactionType, pollMs?: number | false) {
  return useQuery({
    queryKey: qk.transactions(page, pageSize, type),
    queryFn: () => unwrap(api.GET("/billing/transactions", { params: { query: { page, page_size: pageSize, ...(type && { type }) } } })),
    placeholderData: keepPreviousData,
    refetchInterval: pollMs ?? false,
  });
}

/** The latest 100 ledger rows, for spend rate and recent peak on the talk-time gauge. */
export function useRecentTransactions() {
  return useQuery({
    queryKey: [...qk.transactionsAll, "recent"] as const,
    queryFn: () => unwrap(api.GET("/billing/transactions", { params: { query: { page: 1, page_size: 100 } } })),
    staleTime: 30_000,
  });
}

export function useUsage(from: string, to: string, enabled = true) {
  return useQuery({
    queryKey: qk.usage(from, to),
    queryFn: () => unwrap(api.GET("/usage", { params: { query: { from, to } } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCatalog() {
  return useQuery({
    queryKey: qk.catalog,
    queryFn: () => unwrap(api.GET("/pricing/catalog")),
    staleTime: 5 * 60_000,
  });
}

export function useQuote(req: QuoteRequest | null) {
  return useQuery({
    queryKey: req ? qk.quote(req) : ["pricing", "quote", "idle"],
    queryFn: () => unwrap(api.POST("/pricing/quote", { body: req! })),
    enabled: req !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
