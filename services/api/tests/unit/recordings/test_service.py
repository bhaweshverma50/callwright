"""Recording links (006 T026, FR-011, research R9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.recordings.service import recording_link

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
BUCKET = "callwright-recordings"


class Signer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str | None]] = []

    def presign_get(self, bucket: str, key: str, ttl_s: int, download_name: str | None = None) -> str:
        self.calls.append((bucket, key, ttl_s, download_name))
        return f"https://storage.test/{key}?ttl={ttl_s}"


def _call(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "id": "call_01JABCDEFGHJKMNPQRSTVWXYZ0",
        "status": "completed",
        "recording_status": "available",
        "recording_key": "ws_1/call_01JABCDEFGHJKMNPQRSTVWXYZ0.ogg",
        "billable_seconds": 271,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_inline_link_expires_within_ten_minutes() -> None:
    signer = Signer()
    link = recording_link(_call(), signer, BUCKET, ttl_s=900, disposition="inline", now=NOW)
    assert signer.calls == [(BUCKET, "ws_1/call_01JABCDEFGHJKMNPQRSTVWXYZ0.ogg", 600, None)]
    assert datetime.fromisoformat(link["expires_at"]) <= NOW + timedelta(seconds=600)
    assert link["content_type"] == "audio/ogg"
    assert link["filename"] == "call_01JABCDEFGHJKMNPQRSTVWXYZ0.ogg"
    assert link["duration_s"] == 271


def test_attachment_names_the_file_after_the_call() -> None:
    signer = Signer()
    recording_link(
        _call(recording_key="k/x.mp3"), signer, BUCKET, ttl_s=300, disposition="attachment", now=NOW
    )
    assert signer.calls == [(BUCKET, "k/x.mp3", 300, "call_01JABCDEFGHJKMNPQRSTVWXYZ0.mp3")]


def test_processing_is_409() -> None:
    with pytest.raises(ProblemError) as exc:
        recording_link(
            _call(recording_status="recording"), Signer(), BUCKET, ttl_s=600, disposition="inline", now=NOW
        )
    assert (exc.value.status, exc.value.code) == (409, "recording_processing")


def test_retention_deleted_is_410() -> None:
    with pytest.raises(ProblemError) as exc:
        recording_link(_call(recording_key=None), Signer(), BUCKET, ttl_s=600, disposition="inline", now=NOW)
    assert (exc.value.status, exc.value.code) == (410, "recording_deleted")


@pytest.mark.parametrize("status", ["none", "failed", "not_recorded"])
def test_no_recording_is_404(status: str) -> None:
    with pytest.raises(ProblemError) as exc:
        recording_link(
            _call(recording_status=status), Signer(), BUCKET, ttl_s=600, disposition="inline", now=NOW
        )
    assert (exc.value.status, exc.value.code) == (404, "not_recorded")
