/**
 * Datasets (spec 008 US5): named lists of completed live calls of one agent, used as regression
 * suites. Items load page by page with a total (FR-036).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";
import type { Paged } from "./simulations";

type S = components["schemas"];

export type Dataset = S["Dataset"];
export type DatasetItem = S["DatasetItem"];
export type AddItemsResult = S["AddItemsResult"];
export type InvalidReason = AddItemsResult["invalid"][number]["reason"];

export const DATASETS_PAGE_SIZE = 20;
export const ITEMS_PAGE_SIZE = 50;

export const datasetKeys = {
  all: ["datasets"] as const,
  list: (agentId: string, page: number) => ["datasets", "list", { agentId, page }] as const,
  forAgent: (agentId: string) => ["datasets", "for-agent", agentId] as const,
  detail: (id: string) => ["datasets", "detail", id] as const,
  items: (id: string, page: number) => ["datasets", "items", id, page] as const,
};

export const INVALID_REASONS: Record<InvalidReason, string> = {
  not_found: "Call not found",
  wrong_agent: "Belongs to another agent",
  simulated_call: "Simulated calls cannot be added",
  not_completed: "The call did not complete",
  unavailable: "Transcript removed by retention",
};

export function useDatasets(agentId: string | null, page: number) {
  return useQuery({
    queryKey: datasetKeys.list(agentId ?? "", page),
    queryFn: () =>
      unwrap(api.GET("/datasets", { params: { query: { page, page_size: DATASETS_PAGE_SIZE, ...(agentId && { agent_id: agentId }) } } })) as Promise<
        Paged<Dataset>
      >,
    placeholderData: keepPreviousData,
  });
}

/** Up to 100 datasets of one agent, for the "Add to dataset" menu. */
export function useAgentDatasets(agentId: string | null, enabled = true) {
  return useQuery({
    queryKey: datasetKeys.forAgent(agentId ?? ""),
    queryFn: async () =>
      ((await unwrap(api.GET("/datasets", { params: { query: { agent_id: agentId!, page: 1, page_size: 100 } } }))) as Paged<Dataset>).items,
    enabled: enabled && Boolean(agentId),
    staleTime: 15_000,
  });
}

export function useDataset(id: string | undefined) {
  return useQuery({
    queryKey: datasetKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/datasets/{dataset_id}", { params: { path: { dataset_id: id! } } })) as Promise<Dataset>,
    enabled: Boolean(id),
    retry: false,
  });
}

export function useDatasetItems(id: string | undefined, page: number) {
  return useQuery({
    queryKey: datasetKeys.items(id ?? "", page),
    queryFn: () =>
      unwrap(
        api.GET("/datasets/{dataset_id}/items", { params: { path: { dataset_id: id! }, query: { page, page_size: ITEMS_PAGE_SIZE } } }),
      ) as Promise<Paged<DatasetItem>>,
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
  });
}

export function createDataset(body: { name: string; agent_id: string; description?: string | null; call_ids?: string[] }) {
  return unwrap(api.POST("/datasets", { body })) as Promise<Dataset & { add_result?: AddItemsResult }>;
}

export function updateDataset(id: string, body: { name?: string; description?: string | null }) {
  return unwrap(api.PATCH("/datasets/{dataset_id}", { params: { path: { dataset_id: id } }, body })) as Promise<Dataset>;
}

export function deleteDataset(id: string) {
  return unwrap(api.DELETE("/datasets/{dataset_id}", { params: { path: { dataset_id: id } } }));
}

export function addDatasetItems(id: string, callIds: string[]) {
  return unwrap(
    api.POST("/datasets/{dataset_id}/items", { params: { path: { dataset_id: id } }, body: { call_ids: callIds } }),
  ) as Promise<AddItemsResult>;
}

export function removeDatasetItem(id: string, callId: string) {
  return unwrap(api.DELETE("/datasets/{dataset_id}/items/{call_id}", { params: { path: { dataset_id: id, call_id: callId } } }));
}

export function evaluateDataset(id: string, onlyMissing: boolean, key: string) {
  return unwrap(
    api.POST("/datasets/{dataset_id}/evaluate", {
      params: { path: { dataset_id: id }, header: { "Idempotency-Key": key } },
      body: { only_missing: onlyMissing },
    }),
  ) as Promise<{ enqueued: number; skipped_up_to_date?: number; skipped_unavailable: number }>;
}

/** "3 added, 1 already in the dataset, 1 skipped: Belongs to another agent". */
export function describeAddResult(r: AddItemsResult): string {
  const parts = [`${r.added} added`];
  if (r.skipped_duplicates) parts.push(`${r.skipped_duplicates} already in the dataset`);
  if (r.skipped_invalid) {
    const reasons = [...new Set(r.invalid.map((i) => INVALID_REASONS[i.reason]))];
    parts.push(`${r.skipped_invalid} skipped: ${reasons.join("; ").toLowerCase()}`);
  }
  return parts.join(", ");
}
