import type { Problem } from "./types";

/** Any failed API call. `problem` is the RFC 9457 body when the server sent one. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(status: number, problem: Problem) {
    super(problem.title || "Request failed");
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
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

/** Network failure (no response): reported as status 0 with code `network`. */
export function networkError(): ApiError {
  return new ApiError(0, {
    type: "https://callwright.dev/problems/network",
    title: "Network error",
    status: 0,
    code: "network",
  });
}

/** Turns an unknown error body into a Problem without trusting its shape. */
export function toProblem(status: number, body: unknown): Problem {
  if (body && typeof body === "object" && "title" in body) {
    const p = body as Partial<Problem>;
    return {
      type: p.type ?? "about:blank",
      title: String(p.title),
      status: typeof p.status === "number" ? p.status : status,
      ...(p.detail !== undefined && { detail: String(p.detail) }),
      ...(p.code !== undefined && { code: String(p.code) }),
      ...(p.retry_after_s !== undefined && { retry_after_s: Number(p.retry_after_s) }),
      ...(p.trace_id !== undefined && { trace_id: String(p.trace_id) }),
      ...(Array.isArray(p.errors) && { errors: p.errors }),
    };
  }
  return { type: "about:blank", title: "Request failed", status };
}
