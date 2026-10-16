"""``core/livekit.py`` against a real media server (003 T012). Skipped unless ``LIVEKIT_TEST_URL``
points at a dev server, for example::

    docker run --rm -d --name lk-api -p 7981:7880 livekit/livekit-server --dev --bind 0.0.0.0
    LIVEKIT_TEST_URL=ws://localhost:7981 uv run pytest tests/integration/test_livekit_live.py

The dev server has no egress service, so a recording request must fail as ``LiveKitError``.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from livekit import api as lk

from app.core.livekit import EgressTarget, LiveKitClient, LiveKitError, http_url
from tests.conftest import make_settings

URL = os.environ.get("LIVEKIT_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="LIVEKIT_TEST_URL not set (needs livekit-server --dev)")


async def test_room_dispatch_token_and_cleanup() -> None:
    assert URL is not None
    settings = make_settings(
        livekit_mode="live", livekit_url=URL, livekit_api_key="devkey", livekit_api_secret="secret"
    )
    client = LiveKitClient(settings)
    room = f"call-test-{uuid.uuid4().hex[:8]}"
    admin = lk.LiveKitAPI(http_url(URL), "devkey", "secret")
    try:
        await client.create_room(room, metadata=json.dumps({"call_id": "call_x"}))
        rooms = await admin.room.list_rooms(lk.ListRoomsRequest(names=[room]))
        assert [r.name for r in rooms.rooms] == [room]

        dispatch_id = await client.dispatch_agent(room, "callwright-voice", {"call_id": "call_x"})
        # The dev server adds an anonymous dispatch for automatic-dispatch workers; the voice
        # worker registers with an explicit agent name and only takes the named one.
        dispatches = [d for d in await admin.agent_dispatch.list_dispatch(room) if d.agent_name]
        assert [(d.id, d.agent_name, json.loads(d.metadata)) for d in dispatches] == [
            (dispatch_id, "callwright-voice", {"call_id": "call_x"})
        ]

        token = client.join_token(room=room, identity="web-usr-abc")
        claims = lk.TokenVerifier("devkey", "secret").verify(token)
        assert claims.video is not None and claims.video.room == room and claims.video.room_join

        with pytest.raises(LiveKitError):
            await client.start_audio_recording(room, EgressTarget("bucket", f"recordings/ws/{room}.mp4"))

        await client.delete_room(room)
        assert (await admin.room.list_rooms(lk.ListRoomsRequest(names=[room]))).rooms == []
        await client.delete_room(room)  # already gone: no error
    finally:
        await admin.aclose()
        await client.aclose()
