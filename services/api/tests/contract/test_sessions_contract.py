"""POST /v1/sessions/web-call against contracts/sessions.yaml (003 T021, T031, T052)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import jwt
from fastapi import FastAPI

from app.calls import ports
from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import Runtime, agent_config, idem, owner_sql, set_concurrency, start_web_call

URL = "/v1/sessions/web-call"


async def test_201_session_and_token(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    response = check(
        await start_web_call(
            client,
            account.headers,
            agent.agent_id,
            version="draft",
            dynamic_variables={"customer_name": "Priya", "call_id": "nope"},
            metadata={"crm_id": "42"},
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["agent_version_id"] == agent.draft.version_id
    assert body["room_name"] == f"call-{body['call_id']}"
    assert body["ignored_overrides"] == ["call_id"]
    assert body["server_url"] == app.state.settings.livekit_client_url
    # The token joins this room only, publishing the microphone and data (R17).
    claims = jwt.decode(
        body["participant_token"],
        app.state.settings.livekit_api_secret.get_secret_value(),
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    video = claims["video"]
    assert video["room"] == body["room_name"] and video["roomJoin"] is True
    assert video["canPublishSources"] == ["microphone"] and video["canPublishData"] is True
    assert claims["exp"] - claims["nbf"] == 15 * 60
    assert claims["sub"].startswith(f"web-{account.user_id}-")
    # Room created and the worker dispatched with the call id only.
    assert body["room_name"] in runtime.livekit.rooms
    assert (body["room_name"], "callwright-voice", {"call_id": body["call_id"]}) in runtime.livekit.dispatches


async def test_replay_with_the_same_key(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    headers = {**account.headers, **idem()}
    first = check(await client.post(URL, json={"agent_id": agent.agent_id}, headers=headers))
    second = check(await client.post(URL, json={"agent_id": agent.agent_id}, headers=headers))
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert owner_sql("select count(*) from calls where agent_id = %s", (agent.agent_id,)) == [(1,)]
    other_body = check(
        await client.post(URL, json={"agent_id": agent.agent_id, "version": "published"}, headers=headers)
    )
    assert other_body.status_code == 422 and other_body.json()["code"] == "idempotency_key_reused"


async def test_400_without_idempotency_key(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    response = check(await client.post(URL, json={"agent_id": agent.agent_id}, headers=account.headers))
    assert response.status_code == 400
    short = check(
        await client.post(
            URL, json={"agent_id": agent.agent_id}, headers={**account.headers, "Idempotency-Key": "x"}
        )
    )
    assert short.status_code == 400


async def test_401(client: httpx.AsyncClient, runtime: Runtime) -> None:
    response = check(
        await client.post(URL, json={"agent_id": "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"}, headers=idem())
    )
    assert response.status_code == 401


async def test_402_insufficient_credit_with_call_id(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    await runtime.set_balance(account.workspace_id, Decimal(0))
    response = check(await start_web_call(client, account.headers, agent.agent_id))
    assert response.status_code == 402
    body = response.json()
    assert (
        body["type"].endswith("/insufficient-credit") and body["disconnect_reason"] == "insufficient_credit"
    )
    assert owner_sql("select status, disconnect_reason from calls where id = %s", (body["call_id"],)) == [
        ("failed", "insufficient_credit")
    ]
    assert runtime.livekit.dispatches == [] or all(
        m["call_id"] != body["call_id"] for _, _, m in runtime.livekit.dispatches
    )


async def test_403_email_unverified(client: httpx.AsyncClient, account: Account, runtime: Runtime) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    owner_sql("update users set email_verified_at = null where id = %s", (account.user_id,))
    try:
        response = check(await start_web_call(client, account.headers, agent.agent_id))
        assert response.status_code == 403
        assert response.json()["type"].endswith("/email-unverified")
    finally:
        owner_sql("update users set email_verified_at = now() where id = %s", (account.user_id,))


async def test_404_unknown_agent_and_version(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    missing = check(await start_web_call(client, account.headers, "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"))
    assert missing.status_code == 404
    agent = runtime.versions.add_agent(account.workspace_id)
    other = runtime.versions.add_agent(account.workspace_id)
    wrong_version = check(
        await start_web_call(client, account.headers, agent.agent_id, version=other.draft.version_id)
    )
    assert wrong_version.status_code == 404
    explicit = check(
        await start_web_call(client, account.headers, agent.agent_id, version=agent.draft.version_id)
    )
    assert explicit.status_code == 201


async def test_409_agent_not_published(client: httpx.AsyncClient, account: Account, runtime: Runtime) -> None:
    agent = runtime.versions.add_agent(account.workspace_id, published=False)
    response = check(await start_web_call(client, account.headers, agent.agent_id, version="published"))
    assert response.status_code == 409
    assert response.json()["type"].endswith("/agent-not-published")


async def test_422_variables_vendor_and_flow(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    bad_name = check(
        await start_web_call(client, account.headers, agent.agent_id, dynamic_variables={"1bad": "x"})
    )
    assert bad_name.status_code == 422
    too_long = check(
        await start_web_call(client, account.headers, agent.agent_id, dynamic_variables={"a": "x" * 2001})
    )
    assert too_long.status_code == 422
    too_many = check(
        await start_web_call(
            client, account.headers, agent.agent_id, dynamic_variables={f"v{i}": "x" for i in range(51)}
        )
    )
    assert too_many.status_code == 422
    vendor = runtime.versions.add_agent(
        account.workspace_id, agent_config(stt={"provider": "whisperco", "model": "w1"})
    )
    unsupported = check(await start_web_call(client, account.headers, vendor.agent_id))
    assert unsupported.status_code == 422
    body = unsupported.json()
    assert (
        body["type"].endswith("/unsupported-vendor")
        and body["diagnostic"] == "unsupported_vendor:stt/whisperco"
    )
    # The refusal path stays for a worker build without the 004 runtime.
    ports.set_flow_runtime_available(False)
    flow = runtime.versions.add_agent(account.workspace_id, agent_type="flow")
    refused = check(await start_web_call(client, account.headers, flow.agent_id))
    assert refused.status_code == 422 and refused.json()["type"].endswith("/flow-runtime-unavailable")


async def test_429_concurrency_limit(client: httpx.AsyncClient, account: Account, runtime: Runtime) -> None:
    set_concurrency(account.workspace_id, 1)
    agent = runtime.versions.add_agent(account.workspace_id)
    assert check(await start_web_call(client, account.headers, agent.agent_id)).status_code == 201
    response = check(await start_web_call(client, account.headers, agent.agent_id))
    assert response.status_code == 429
    body = response.json()
    assert body["type"].endswith("/concurrency-limit") and body["disconnect_reason"] == "concurrency_limit"


async def test_503_media_server_down(client: httpx.AsyncClient, account: Account, runtime: Runtime) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    runtime.livekit.fail_next.add("dispatch_agent")
    response = check(await start_web_call(client, account.headers, agent.agent_id))
    assert response.status_code == 503
    call_id = response.json()["call_id"]
    assert owner_sql("select status, diagnostic, billable_seconds from calls where id = %s", (call_id,)) == [
        ("failed", "room_unavailable", 0)
    ]
    assert f"call-{call_id}" in runtime.livekit.deleted
