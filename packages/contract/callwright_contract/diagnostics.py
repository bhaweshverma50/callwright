"""Diagnostic codes both services store on a call (003 data-model section 1, ``calls.diagnostic``):
a code, optionally followed by ``:`` and its parts joined by ``/`` (``vendor_error:tts/cartesia``,
``unsupported_vendor:stt/deepgram/nova-9``, ``stt_language_unsupported:assemblyai/ja``).

The worker sets them when it ends or fails a call; the API sets the same ones when it refuses a
call at admission or reaps one. Codes use underscores only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# A vendor failed during the call: ``vendor_error:<kind>/<provider>``.
VENDOR_ERROR: Final = "vendor_error"
# A vendor or model the worker cannot run: ``unsupported_vendor:<kind>/<provider>[/<model>]``.
UNSUPPORTED_VENDOR: Final = "unsupported_vendor"
# No speech recognition model of the provider covers the language:
# ``stt_language_unsupported:<provider>/<language>``.
STT_LANGUAGE_UNSUPPORTED: Final = "stt_language_unsupported"
FLOW_NOT_COMPILED: Final = "flow_not_compiled"
FLOW_RUNTIME_UNAVAILABLE: Final = "flow_runtime_unavailable"
CALLER_NEVER_JOINED: Final = "caller_never_joined"
OUTBOUND_DIAL_MISSING: Final = "outbound_dial_missing"


def diagnostic(code: str, *parts: str | None) -> str:
    """``code``, or ``code:part/part`` with the parts that are set."""
    given = [p for p in parts if p]
    return f"{code}:{'/'.join(given)}" if given else code


@dataclass(frozen=True)
class Diagnostic:
    code: str
    parts: tuple[str, ...] = ()


def parse(text: str) -> Diagnostic:
    code, _, rest = text.partition(":")
    return Diagnostic(code, tuple(rest.split("/")) if rest else ())
