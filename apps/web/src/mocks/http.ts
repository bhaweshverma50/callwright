/**
 * Response helpers shared by every mock handler, so mock bodies look like the API's: problems are
 * RFC 9457 with the API's type URL and default titles (services/api/app/core/errors.py), and lists
 * use the contract's page envelope.
 */
import { HttpResponse, type JsonBodyType } from "msw";
import type { FieldError, PageMeta, Problem } from "../api/types";
import { env } from "../lib/env";

export const url = (path: string) => `${env.apiBaseUrl}${path}`;

/** Contract types allow `undefined` members, which msw's JSON body type does not; the body is serialised as JSON either way. */
export function json<T>(body: T, status = 200, headers: Record<string, string> = {}) {
  return HttpResponse.json(body as unknown as JsonBodyType, { status, headers });
}

const PROBLEM_BASE = "https://callwright.dev/problems/";
const STATUS_TITLES: Record<number, string> = {
  400: "Bad request",
  401: "Not signed in",
  403: "Not allowed",
  404: "Not found",
  405: "Method not allowed",
  409: "Conflict",
  412: "Precondition failed",
  422: "Request is not valid",
  429: "Too many requests",
  500: "Something went wrong",
  503: "Service unavailable",
};

export type ProblemExtra = Partial<Problem> & Record<string, unknown>;

/** A problem response. `extra` is the detail text, or extra members (detail, errors, retry_after_s, trace_id, feature fields). */
export function problem(status: number, code: string, title: string, extra: string | ProblemExtra = {}) {
  const fields = typeof extra === "string" ? { detail: extra } : extra;
  const body = { type: PROBLEM_BASE + code.replace(/_/g, "-"), title, status, code, ...fields };
  const headers: Record<string, string> = { "content-type": "application/problem+json" };
  if (fields.retry_after_s) headers["retry-after"] = String(fields.retry_after_s);
  return json(body, status, headers);
}

/** A problem with the API's default title for the status and `detail` saying what went wrong. */
export function problemDetail(status: number, code: string, detail: string, extra: ProblemExtra = {}) {
  return problem(status, code, STATUS_TITLES[status] ?? "Error", { detail, ...extra });
}

export const unauthorized = () => problem(401, "unauthorized", "Sign in required");

/** 422 with field errors, as the API's request validation sends it. */
export function validation(errors: FieldError[], detail?: string) {
  return problem(422, "validation_failed", "Request failed validation", { ...(detail && { detail }), errors });
}

/** 422 for one field: the message is both the detail and the field error. */
export const invalid = (pointer: string, message: string, code = "invalid") => validation([{ pointer, code, message }], message);

/** One page of `rows` for the `page` and `page_size` query parameters (page size capped at 100, as in core.yaml). */
export function page<T>(rows: T[], query: Request | URLSearchParams, defaultSize = 20): PageMeta & { items: T[] } {
  const q = query instanceof URLSearchParams ? query : new URL(query.url).searchParams;
  const pageNo = Math.max(1, Number(q.get("page") ?? 1));
  const size = Math.min(100, Math.max(1, Number(q.get("page_size") ?? defaultSize)));
  return {
    items: rows.slice((pageNo - 1) * size, pageNo * size),
    total: rows.length,
    page: pageNo,
    page_size: size,
    total_pages: Math.ceil(rows.length / size),
  };
}
