import type { components } from "./schema";
import type { HttpMethod, paths, Problem, ProblemFor } from "./types";

type S = components["schemas"];

/**
 * A problem body as the server sent it: the RFC 9457 fields plus every extension the operation
 * declares (active_call_count, reason, current_revision, issues and so on).
 */
export type ProblemBody = Problem & Record<string, unknown>;

/** Every problem schema the contract names: ActiveCallsProblem, PolicyBlockedProblem, ... */
export type ProblemKind = Extract<keyof S, `${string}Problem`>;

/**
 * A problem read as the contract schema `K`. Extension fields stay optional: the body is only as
 * good as what arrived, and an error with another shape can reach the same handler.
 */
export type ProblemOf<K extends ProblemKind> = Problem & Partial<Omit<S[K], keyof Problem>>;

/** Any failed API call. `problem` is the full problem body when the server sent one. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemBody;

  constructor(status: number, problem: Problem) {
    super(problem.title || "Request failed");
    this.name = "ApiError";
    this.status = status;
    this.problem = problem as ProblemBody;
  }

  get code(): string | undefined {
    return this.problem.code;
  }
  get traceId(): string | undefined {
    return this.problem.trace_id;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/**
 * The problem body of `err` typed as the contract schema `kind`, or undefined for anything that is
 * not an API error. Check the status or code first: the kind names how to read the body, it does
 * not test it.
 */
export function problemAs<K extends ProblemKind>(err: unknown, kind: K): ProblemOf<K> | undefined;
export function problemAs(err: unknown): ProblemBody | undefined {
  return isApiError(err) ? err.problem : undefined;
}

/** Network failure (no response): reported as status 0 with code `network`. */
export function networkError(): ApiError {
  return new ApiError(0, {
    type: "https://callwright.dev/problems/network",
    title: "Network error",
    status: 0,
    code: "network",
  });
}

/**
 * Turns an unknown error body into a Problem without trusting its shape: the standard fields are
 * normalised and every other field is kept as sent, so typed readers (problemAs) see extensions.
 */
export function toProblem(status: number, body: unknown): Problem {
  if (body && typeof body === "object" && "title" in body) {
    const p = body as Partial<Problem> & Record<string, unknown>;
    const { detail, code, retry_after_s, trace_id, errors, ...rest } = p;
    return {
      ...rest,
      type: p.type ?? "about:blank",
      title: String(p.title),
      status: typeof p.status === "number" ? p.status : status,
      ...(detail !== undefined && { detail: String(detail) }),
      ...(code !== undefined && { code: String(code) }),
      ...(retry_after_s !== undefined && { retry_after_s: Number(retry_after_s) }),
      ...(trace_id !== undefined && { trace_id: String(trace_id) }),
      ...(Array.isArray(errors) && { errors }),
    };
  }
  return { type: "about:blank", title: "Request failed", status };
}

/**
 * The problem body `path`/`method` declares for `status`, when `err` failed with that status. For
 * operations whose contract describes the body inline instead of naming a schema.
 */
export function problemFor<P extends keyof paths, M extends HttpMethod, St extends number>(
  err: unknown,
  path: P,
  method: M,
  status: St,
): (Problem & Partial<Omit<ProblemFor<P, M, St>, keyof Problem>>) | undefined;
export function problemFor(err: unknown, _path: string, _method: string, status: number): ProblemBody | undefined {
  return isApiError(err) && err.status === status ? err.problem : undefined;
}
