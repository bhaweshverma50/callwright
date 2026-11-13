/**
 * Test cases and test runs (spec 008 US1): categories, cases, AI drafts, import and export, judged
 * runs and manual overrides. Types come from specs/008-testing-simulation/contracts; hooks are
 * TanStack Query. Paid POSTs take an Idempotency-Key from the caller (see paid.ts).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";
import type { ResponseOf } from "./types";
import { bodyLimits } from "../lib/contract.gen";

type S = components["schemas"];

export type TestCategory = S["TestCategory"];
export type TestCase = S["TestCase"];
export type TestCaseCreate = S["TestCaseCreate"];
export type TestCaseUpdate = S["TestCaseUpdate"];
export type TestCaseImportRow = S["TestCaseImportRow"];
export type TestCaseFile = S["TestCaseFile"];
export type TestTarget = S["TestTarget"];
export type ToolCallRecord = S["ToolCallRecord"];
export type TestRun = S["TestRun"];
export type TestResult = S["TestResult"];
export type TestRunDetail = ResponseOf<"/test-runs/{test_run_id}", "get">;
export type ImportOutcome = ResponseOf<"/test-cases/import", "post">;

export const TEST_POLL_MS = 3_000;

/** Palette for custom categories (FR-032): a new category picks one of these; seeds have fixed entries. */
export const CATEGORY_PALETTE = bodyLimits["POST /test-categories"].color.enum;

export const testingKeys = {
  all: ["testing"] as const,
  categories: ["testing", "categories"] as const,
  cases: (agentId: string) => ["testing", "cases", agentId] as const,
  casesPage: (agentId: string, category: string, page: number, pageSize: number) =>
    ["testing", "cases", agentId, { category, page, pageSize }] as const,
  runs: (agentId: string) => ["testing", "runs", agentId] as const,
  run: (runId: string) => ["testing", "run", runId] as const,
};

const byName = (a: TestCategory, b: TestCategory) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });

/** Categories alphabetically by name (the API sorts too; this keeps optimistic adds in order). */
export function useTestCategories() {
  return useQuery({
    queryKey: testingKeys.categories,
    queryFn: async () => (await unwrap(api.GET("/test-categories"))).items.slice().sort(byName),
    staleTime: 60_000,
  });
}

export type CategoryColor = (typeof CATEGORY_PALETTE)[number];

export function createTestCategory(body: { name: string; color?: CategoryColor }) {
  return unwrap(api.POST("/test-categories", { body }));
}

export function useTestCases(agentId: string, category: string | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: testingKeys.casesPage(agentId, category ?? "", page, pageSize),
    queryFn: () =>
      unwrap(
        api.GET("/test-cases", {
          params: { query: { agent_id: agentId, page, page_size: pageSize, ...(category && { category }) } },
        }),
      ),
    enabled: Boolean(agentId),
    placeholderData: keepPreviousData,
  });
}

export function createTestCase(body: TestCaseCreate) {
  return unwrap(api.POST("/test-cases", { body }));
}

export function updateTestCase(id: string, body: TestCaseUpdate) {
  return unwrap(api.PATCH("/test-cases/{test_case_id}", { params: { path: { test_case_id: id } }, body }));
}

export function deleteTestCase(id: string) {
  return unwrap(api.DELETE("/test-cases/{test_case_id}", { params: { path: { test_case_id: id } } }));
}

export function importTestCases(agentId: string, rows: TestCaseImportRow[], dryRun: boolean) {
  return unwrap(
    api.POST("/test-cases/import", { body: { agent_id: agentId, dry_run: dryRun, format: "callwright.test_cases.v1", test_cases: rows } }),
  );
}

export function exportTestCases(agentId: string, template = false) {
  return unwrap(api.GET("/test-cases/export", { params: { query: { agent_id: agentId, template } } }));
}

export function generateTestCases(body: { agent_id: string; category: string | null; count: number; guidance: string | null }, key: string) {
  return unwrap(api.POST("/test-cases/generate", { params: { header: { "Idempotency-Key": key } }, body }));
}

export const isRunActive = (status: TestRun["status"] | undefined) => status === "queued" || status === "running";

export function useTestRuns(agentId: string) {
  return useQuery({
    queryKey: testingKeys.runs(agentId),
    queryFn: () => unwrap(api.GET("/test-runs", { params: { query: { agent_id: agentId, page: 1, page_size: 20 } } })),
    enabled: Boolean(agentId),
    refetchInterval: (q) => (q.state.data?.items.some((r) => isRunActive(r.status)) ? TEST_POLL_MS : false),
  });
}

export function useTestRun(runId: string | null) {
  return useQuery({
    queryKey: testingKeys.run(runId ?? ""),
    queryFn: () => unwrap(api.GET("/test-runs/{test_run_id}", { params: { path: { test_run_id: runId! } } })),
    enabled: Boolean(runId),
    refetchInterval: (q) => (isRunActive(q.state.data?.status) ? TEST_POLL_MS : false),
  });
}

export function startTestRun(
  body: { agent_id: string; test_case_ids?: string[]; category?: string; target?: TestTarget; judge_model?: string },
  key: string,
) {
  return unwrap(api.POST("/test-runs", { params: { header: { "Idempotency-Key": key } }, body }));
}

export function cancelTestRun(runId: string) {
  return unwrap(api.POST("/test-runs/{test_run_id}/cancel", { params: { path: { test_run_id: runId } } }));
}

export function overrideTestResult(runId: string, caseId: string, override_status: "passed" | "failed" | null, override_note: string | null = null) {
  return unwrap(
    api.PATCH("/test-runs/{test_run_id}/results/{test_case_id}", {
      params: { path: { test_run_id: runId, test_case_id: caseId } },
      body: { override_status, override_note },
    }),
  );
}

export function exportTestRun(runId: string) {
  return unwrap(api.GET("/test-runs/{test_run_id}/export", { params: { path: { test_run_id: runId } } }));
}
