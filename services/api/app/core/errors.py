"""RFC 9457 problem+json responses (T010, T091).

* ``ProblemError`` is raised by services and routes; the handler serialises it.
* Request validation errors become 422 with every failing field in ``errors``.
* Unknown routes and methods become 404/405 problems.
* Any other exception becomes a generic 500 with a ``trace_id``; the exception is logged
  server-side and its text (database, driver or vendor) never reaches the response (FR-019).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://callwright.dev/problems/"
PROBLEM_JSON = "application/problem+json"

logger = logging.getLogger("app.errors")

_TITLES = {
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
}

# Pydantic error types mapped to the stable FieldError codes in contracts/core.yaml.
_FIELD_CODES = {
    "missing": "required",
    "extra_forbidden": "unknown_field",
    "string_too_short": "out_of_range",
    "string_too_long": "out_of_range",
    "too_short": "out_of_range",
    "too_long": "out_of_range",
    "greater_than": "out_of_range",
    "greater_than_equal": "out_of_range",
    "less_than": "out_of_range",
    "less_than_equal": "out_of_range",
}
_CUSTOM_CODES = {"out_of_range", "invalid_format", "required", "not_in_catalog", "too_precise"}


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str | None = None,
        detail: str | None = None,
        *,
        retry_after_s: int | None = None,
        errors: Sequence[Mapping[str, str]] | None = None,
        headers: Mapping[str, str] | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title or code)
        self.status = status
        self.code = code
        self.title = title or _TITLES.get(status, "Error")
        self.detail = detail
        self.retry_after_s = retry_after_s
        self.errors = list(errors) if errors is not None else None
        self.headers = dict(headers or {})
        self.extra = dict(extra or {})

    def body(self, instance: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": PROBLEM_BASE + self.code.replace("_", "-"),
            "title": self.title,
            "status": self.status,
            "code": self.code,
        }
        if self.detail:
            body["detail"] = self.detail
        if instance:
            body["instance"] = instance
        if self.retry_after_s is not None:
            body["retry_after_s"] = self.retry_after_s
        if self.errors is not None:
            body["errors"] = self.errors
        body.update(self.extra)
        return body


def not_found(kind: str = "record") -> ProblemError:
    return ProblemError(404, "not_found", "Not found", f"No {kind} with that id exists in this workspace.")


def unauthorized(detail: str = "Sign in to continue.", code: str = "unauthorized") -> ProblemError:
    return ProblemError(401, code, "Not signed in", detail, headers={"WWW-Authenticate": "Bearer"})


def forbidden(detail: str = "You are not allowed to do this.", code: str = "forbidden") -> ProblemError:
    return ProblemError(403, code, "Not allowed", detail)


def validation_failed(errors: Sequence[Mapping[str, str]]) -> ProblemError:
    return ProblemError(422, "validation_failed", "Request is not valid", errors=errors)


def field_error(pointer: str, code: str, message: str) -> dict[str, str]:
    return {"pointer": pointer, "code": code, "message": message}


def too_many_requests(retry_after_s: int, detail: str) -> ProblemError:
    retry_after_s = max(1, retry_after_s)
    return ProblemError(
        429,
        "rate_limited",
        "Too many requests",
        detail,
        retry_after_s=retry_after_s,
        headers={"Retry-After": str(retry_after_s)},
    )


def current_trace_id() -> str:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return uuid.uuid4().hex


def problem_response(problem: ProblemError, request: Request | None = None) -> JSONResponse:
    instance = request.url.path if request is not None else None
    headers = dict(problem.headers)
    return JSONResponse(
        problem.body(instance), status_code=problem.status, media_type=PROBLEM_JSON, headers=headers
    )


def _pointer(loc: Sequence[int | str]) -> str:
    parts = [str(p) for p in loc]
    if parts and parts[0] == "body":
        parts = parts[1:]
    elif parts and parts[0] in {"query", "header", "path", "cookie"}:
        pass
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def _field_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for err in exc.errors():
        etype = str(err.get("type", ""))
        code = etype if etype in _CUSTOM_CODES else _FIELD_CODES.get(etype, "invalid_format")
        message = str(err.get("msg", "Invalid value"))
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        out.append(field_error(_pointer(err.get("loc", ())), code, message))
    return out


async def _problem_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(exc, request)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem_response(validation_failed(_field_errors(exc)), request)


async def _http_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    if status == 404:
        problem = ProblemError(404, "not_found", "Not found", "Nothing exists at this address.")
    elif status == 405:
        problem = ProblemError(405, "method_not_allowed", "Method not allowed")
    else:
        code = _TITLES.get(status, "error").lower().replace(" ", "_")
        problem = ProblemError(status, code, _TITLES.get(status, "Error"))
    if exc.headers:
        problem.headers.update(exc.headers)
    return problem_response(problem, request)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    return unhandled_response(request.url.path, request.method, exc)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)


def unhandled_response(request_path: str, method: str, exc: BaseException) -> JSONResponse:
    trace_id = current_trace_id()
    logger.error("unhandled error on %s %s trace_id=%s", method, request_path, trace_id, exc_info=exc)
    problem = ProblemError(
        500,
        "internal_error",
        "Something went wrong",
        "An unexpected error occurred. Quote the reference to support.",
        extra={"trace_id": trace_id},
    )
    return JSONResponse(problem.body(request_path), status_code=500, media_type=PROBLEM_JSON)


class UnhandledErrorMiddleware:
    """Turns any exception that escapes the routes into the generic 500 problem.

    It sits inside the tracing middleware, so the ``trace_id`` it reports is the request's real
    trace id. Exceptions after the response started are re-raised (nothing safe to send).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def _send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            if started:
                raise
            response = unhandled_response(scope.get("path", ""), scope.get("method", ""), exc)
            await response(scope, receive, send)


class FieldErrorModel(BaseModel):
    pointer: str
    code: str
    message: str


class Problem(BaseModel):
    """RFC 9457 problem body (contracts/core.yaml ``Problem``), for OpenAPI documentation."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None
    retry_after_s: int | None = None
    trace_id: str | None = None
    errors: list[FieldErrorModel] | None = None


_DESCRIPTIONS = {
    400: "Bad request",
    401: "Missing, expired or revoked token",
    402: "Not enough credit",
    403: "Not allowed",
    404: "Not found",
    409: "Conflict",
    422: "Validation failed",
    429: "Rate limited",
}


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` entries for problem statuses (kept in step with the contract)."""
    return {
        status: {"description": _DESCRIPTIONS.get(status, "Problem"), "model": Problem} for status in statuses
    }
