"""Logging setup: plain text for development, one JSON object per line when LOG_JSON=true.

Every record carries the current OpenTelemetry trace id so 500 responses can be traced (FR-019).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

from opentelemetry import trace


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = trace.get_current_span().get_span_context()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else "-"
        return True


# Values of these fields never reach a log line (010 T042): carrier passwords, WhatsApp tokens
# and app secrets, Meta SIP credentials, and bearer tokens.
SECRET_FIELDS = (
    "auth_password",
    "password",
    "access_token",
    "verify_token",
    "app_secret",
    "sip_user_password",
    "hub.verify_token",
    "client_secret",
)
_SECRET_VALUE = re.compile(
    r"(?P<key>(?:" + "|".join(re.escape(f) for f in SECRET_FIELDS) + r"))"
    r"(?P<sep>[\"']?\s*[:=]\s*[\"']?)(?P<value>[^\"'\s,;&}\]]+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")


def redact(text: str) -> str:
    text = _SECRET_VALUE.sub(lambda m: f"{m.group('key')}{m.group('sep')}[redacted]", text)
    return _BEARER.sub(r"\1[redacted]", text)


class RedactSecretsFilter(logging.Filter):
    """Rewrites the formatted message with secret values replaced by ``[redacted]``."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a broken format string is logged as is
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_TraceIdFilter())
    handler.addFilter(RedactSecretsFilter())
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(trace_id)s] %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
