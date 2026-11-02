"""Issue status machine (009 T010; spec FR-019, data-model state transitions).

``transition(status, event)`` returns the next status or raises a 409 problem naming why:

* ``validate``: open or validated to validating (validated means a re-validation).
* ``decided_passed``: validating to validated; ``decided_other`` (failed, inconclusive,
  cancelled, error): validating to open.
* ``new_revision``: open stays open, validated returns to open (the validated fix is no longer
  current); refused while a validation runs.
* ``apply``: validated to applied. ``dismiss``: open, validating or validated to dismissed.
* ``applied`` and ``dismissed`` are final.
"""

from __future__ import annotations

from app.core.errors import ProblemError

STATUSES = ("open", "validating", "validated", "applied", "dismissed")
EVENTS = ("validate", "decided_passed", "decided_other", "new_revision", "apply", "dismiss")
FINAL = ("applied", "dismissed")

_NEXT: dict[tuple[str, str], str] = {
    ("open", "validate"): "validating",
    ("validated", "validate"): "validating",
    ("validating", "decided_passed"): "validated",
    ("validating", "decided_other"): "open",
    ("open", "new_revision"): "open",
    ("validated", "new_revision"): "open",
    ("validated", "apply"): "applied",
    ("open", "dismiss"): "dismissed",
    ("validating", "dismiss"): "dismissed",
    ("validated", "dismiss"): "dismissed",
}


def wrong_status(status: str) -> ProblemError:
    word = "applied" if status == "applied" else "dismissed"
    return ProblemError(
        409,
        "wrong_status",
        "Issue is closed",
        f"This issue is {word} and can no longer change.",
        extra={"issue_status": status},
    )


def refusal(status: str, event: str) -> ProblemError:
    if status in FINAL:
        return wrong_status(status)
    if event == "new_revision" and status == "validating":
        return ProblemError(
            409,
            "validation_running",
            "Validation running",
            "A validation of the current fix is running. Wait for it or cancel it, then draft again.",
        )
    if event == "validate" and status == "validating":
        return ProblemError(
            409,
            "validation_running",
            "Validation running",
            "This fix is already being validated. Wait for the result or cancel it.",
        )
    if event == "apply":
        return ProblemError(
            409,
            "no_passing_validation",
            "Fix not validated",
            "This fix has no passing validation. Validate it, then apply.",
        )
    return ProblemError(
        409,
        "wrong_status",
        "Not allowed now",
        f"An issue that is {status} cannot do that. Reload the issue to see its current state.",
        extra={"issue_status": status},
    )


def transition(status: str, event: str) -> str:
    nxt = _NEXT.get((status, event))
    if nxt is None:
        raise refusal(status, event)
    return nxt
