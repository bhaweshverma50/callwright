"""Issue status machine (009 T009; spec FR-019, data-model state transitions)."""

from __future__ import annotations

import pytest

from app.core.errors import ProblemError
from app.issues.lifecycle import EVENTS, STATUSES, transition

ALLOWED = {
    ("open", "validate"): "validating",
    ("validated", "validate"): "validating",
    ("validating", "decided_passed"): "validated",
    ("validating", "decided_other"): "open",
    ("validated", "new_revision"): "open",
    ("open", "new_revision"): "open",
    ("validated", "apply"): "applied",
    ("open", "dismiss"): "dismissed",
    ("validating", "dismiss"): "dismissed",
    ("validated", "dismiss"): "dismissed",
}


@pytest.mark.parametrize(("status", "event"), sorted(ALLOWED))
def test_allowed_transitions(status: str, event: str) -> None:
    assert transition(status, event) == ALLOWED[(status, event)]


REFUSED = [(s, e) for s in STATUSES for e in EVENTS if (s, e) not in ALLOWED]


@pytest.mark.parametrize(("status", "event"), REFUSED)
def test_refused_transitions(status: str, event: str) -> None:
    with pytest.raises(ProblemError) as exc:
        transition(status, event)
    assert exc.value.status == 409


@pytest.mark.parametrize("final", ["applied", "dismissed"])
def test_final_states_refuse_everything(final: str) -> None:
    for event in EVENTS:
        with pytest.raises(ProblemError) as exc:
            transition(final, event)
        assert exc.value.code == "wrong_status"


def test_drafting_during_validation_says_why() -> None:
    with pytest.raises(ProblemError) as exc:
        transition("validating", "new_revision")
    assert exc.value.code == "validation_running"


def test_apply_without_validation_names_the_blocker() -> None:
    with pytest.raises(ProblemError) as exc:
        transition("open", "apply")
    assert exc.value.code == "no_passing_validation"
