"""Contract tests for knowledge bases (005 T052, T069, T097)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.knowledge import jobs
from app.knowledge.embeddings.fake import FakeEmbeddings
from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.contract.conftest import check
from tests.fixtures import knowledge as fx

MISSING_KB = "kb_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MISSING_DOC = "doc_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MISSING_AGENT = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest_asyncio.fixture(autouse=True)
async def fake_embedder(app: FastAPI) -> AsyncIterator[FakeEmbeddings]:
    embedder = FakeEmbeddings()
    previous = getattr(app.state, "embedder", None)
    app.state.embedder = embedder
    yield embedder
    await jobs.drain()
    app.state.embedder = previous


async def make_kb(
    client: httpx.AsyncClient, account: Account, name: str = "Clinic policies"
) -> dict[str, Any]:
    response = check(
        await client.post(
            "/v1/knowledge-bases",
            json={"name": name, "description": "Refunds, hours, prices"},
            headers=account.headers,
        )
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def upload(
    client: httpx.AsyncClient,
    account: Account,
    kb_id: str,
    data: bytes,
    name: str = "refund_policy.pdf",
    **form: Any,
) -> httpx.Response:
    return check(
        await client.post(
            f"/v1/knowledge-bases/{kb_id}/documents",
            files={"file": (name, data, "application/octet-stream")},
            data={k: str(v).lower() if isinstance(v, bool) else v for k, v in form.items()},
            headers=account.headers,
        )
    )


async def ready_kb(
    client: httpx.AsyncClient, account: Account, name: str = "Clinic policies"
) -> dict[str, Any]:
    kb = await make_kb(client, account, name)
    accepted = await upload(client, account, kb["id"], fx.refund_policy_pdf(), acknowledge_duplicate=True)
    assert accepted.status_code == 202, accepted.text
    await jobs.drain()
    return kb


async def test_kb_crud(client: httpx.AsyncClient, account: Account) -> None:
    kb = await make_kb(client, account)
    assert kb["status"] == "empty" and kb["attachable"] is False and kb["agent_count"] == 0
    duplicate = check(
        await client.post("/v1/knowledge-bases", json={"name": "clinic POLICIES"}, headers=account.headers)
    )
    assert duplicate.status_code == 409
    invalid = check(await client.post("/v1/knowledge-bases", json={"name": ""}, headers=account.headers))
    assert invalid.status_code == 422
    listed = check(await client.get("/v1/knowledge-bases?search=clinic", headers=account.headers)).json()
    assert [k["id"] for k in listed["items"]] == [kb["id"]]
    renamed = check(
        await client.patch(
            f"/v1/knowledge-bases/{kb['id']}", json={"name": "Policies"}, headers=account.headers
        )
    )
    assert renamed.json()["name"] == "Policies"
    assert (
        check(await client.get(f"/v1/knowledge-bases/{MISSING_KB}", headers=account.headers)).status_code
        == 404
    )
    deleted = check(await client.delete(f"/v1/knowledge-bases/{kb['id']}", headers=account.headers))
    assert deleted.json() == {"deleted": True, "detached_agent_ids": []}


async def test_upload_ingests_to_ready(client: httpx.AsyncClient, account: Account) -> None:
    kb = await make_kb(client, account)
    accepted = await upload(client, account, kb["id"], fx.refund_policy_pdf(), display_name="Refunds 2026")
    assert accepted.status_code == 202
    doc = accepted.json()
    assert doc["status"] == "uploaded" and doc["file_type"] == "pdf" and doc["display_name"] == "Refunds 2026"
    await jobs.drain()
    got = check(
        await client.get(f"/v1/knowledge-bases/{kb['id']}/documents/{doc['id']}", headers=account.headers)
    )
    assert (
        got.json()["status"] == "ready" and got.json()["page_count"] == 2 and got.json()["chunk_count"] >= 1
    )
    detail = check(await client.get(f"/v1/knowledge-bases/{kb['id']}", headers=account.headers)).json()
    assert detail["status"] == "ready" and detail["attachable"] and detail["ready_count"] == 1
    listed = check(
        await client.get(f"/v1/knowledge-bases/{kb['id']}/documents", headers=account.headers)
    ).json()
    assert listed["items"][0]["display_name"] == "Refunds 2026"
    default_name = await upload(client, account, kb["id"], fx.policies_docx(), name="policies.docx")
    assert default_name.json()["display_name"] == "policies.docx"


async def test_upload_refusals(client: httpx.AsyncClient, account: Account) -> None:
    kb = await make_kb(client, account)
    assert (await upload(client, account, kb["id"], fx.refund_policy_pdf())).status_code == 202
    same = await upload(client, account, kb["id"], fx.refund_policy_pdf(), name="copy.pdf")
    assert same.status_code == 409 and same.json()["code"] == "duplicate_document"
    other = await make_kb(client, account, "Other")
    elsewhere = await upload(client, account, other["id"], fx.refund_policy_pdf())
    assert elsewhere.status_code == 409 and elsewhere.json()["code"] == "duplicate_elsewhere"
    acknowledged = await upload(
        client, account, other["id"], fx.refund_policy_pdf(), acknowledge_duplicate=True
    )
    assert acknowledged.status_code == 202
    too_big = await upload(client, account, kb["id"], fx.oversize(), name="big.pdf")
    assert too_big.status_code == 413 and too_big.json()["code"] == "file_too_large"
    wrong = await upload(client, account, kb["id"], b"just some text", name="notes.pdf")
    assert wrong.status_code == 415 and wrong.json()["code"] == "unsupported_file_type"
    renamed = await upload(client, account, kb["id"], fx.notes_renamed_pdf(), name="notes_renamed.pdf")
    assert renamed.status_code == 202 and renamed.json()["file_type"] == "docx"
    missing = await upload(client, account, MISSING_KB, fx.policies_docx())
    assert missing.status_code == 404


async def test_quota_refusal(client: httpx.AsyncClient, account: Account, monkeypatch: Any) -> None:
    from app.knowledge import service

    monkeypatch.setattr(service, "MAX_DOCS_PER_KB", 1)
    kb = await make_kb(client, account)
    assert (await upload(client, account, kb["id"], fx.refund_policy_pdf())).status_code == 202
    refused = await upload(client, account, kb["id"], fx.policies_docx(), name="p.docx")
    assert refused.status_code == 422 and refused.json()["code"] == "quota_exceeded"


async def test_check_duplicate_verdicts(client: httpx.AsyncClient, account: Account) -> None:
    kb = await ready_kb(client, account)
    other = await make_kb(client, account, "Other")
    data = fx.refund_policy_pdf()
    digest = hashlib.sha256(data).hexdigest()

    async def verdict(kb_id: str, name: str, sha: str) -> str:
        response = check(
            await client.post(
                f"/v1/knowledge-bases/{kb_id}/documents/check-duplicate",
                json={"file_name": name, "sha256": sha, "file_size": len(data)},
                headers=account.headers,
            )
        )
        result: str = response.json()["verdict"]
        return result

    assert await verdict(kb["id"], "x.pdf", digest) == "blocked_same_kb"
    assert await verdict(other["id"], "x.pdf", digest) == "warn_other_kb"
    assert await verdict(kb["id"], "refund_policy.pdf", "0" * 64) == "warn_same_name"
    assert await verdict(other["id"], "new.pdf", "0" * 64) == "ok"


async def test_document_url_reprocess_and_delete(client: httpx.AsyncClient, account: Account) -> None:
    kb = await make_kb(client, account)
    scanned = (await upload(client, account, kb["id"], fx.scanned_pdf(), name="scan.pdf")).json()
    await jobs.drain()
    failed = check(
        await client.get(f"/v1/knowledge-bases/{kb['id']}/documents/{scanned['id']}", headers=account.headers)
    ).json()
    assert failed["status"] == "failed" and failed["error_code"] == "no_extractable_text"
    retried = check(
        await client.post(
            f"/v1/knowledge-bases/{kb['id']}/documents/{scanned['id']}/reprocess", headers=account.headers
        )
    )
    assert retried.status_code == 202 and retried.json()["status"] == "uploaded"
    await jobs.drain()
    url = check(
        await client.get(
            f"/v1/knowledge-bases/{kb['id']}/documents/{scanned['id']}/url", headers=account.headers
        )
    ).json()
    assert url["url"].startswith("http") and url["expires_at"]
    not_failed = await upload(client, account, kb["id"], fx.refund_policy_pdf())
    await jobs.drain()
    conflict = check(
        await client.post(
            f"/v1/knowledge-bases/{kb['id']}/documents/{not_failed.json()['id']}/reprocess",
            headers=account.headers,
        )
    )
    assert conflict.status_code == 409
    gone = check(
        await client.delete(
            f"/v1/knowledge-bases/{kb['id']}/documents/{scanned['id']}", headers=account.headers
        )
    )
    assert gone.status_code == 204
    again = check(
        await client.delete(
            f"/v1/knowledge-bases/{kb['id']}/documents/{MISSING_DOC}", headers=account.headers
        )
    )
    assert again.status_code == 404


async def test_preview_search(client: httpx.AsyncClient, account: Account) -> None:
    kb = await ready_kb(client, account)
    found = check(
        await client.post(
            f"/v1/knowledge-bases/{kb['id']}/search",
            json={"query": "How many days do I have to ask for a refund?"},
            headers=account.headers,
        )
    ).json()
    assert found["results"] and "14 days" in found["results"][0]["content"]
    assert found["results"][0]["page_from"] == 1 and found["embedding_cache_hit"] is False
    cached = check(
        await client.post(
            f"/v1/knowledge-bases/{kb['id']}/search",
            json={"query": "how many days do I have to ask for a REFUND?"},
            headers=account.headers,
        )
    ).json()
    assert cached["embedding_cache_hit"] is True


async def test_agent_knowledge_attach(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    kb = await ready_kb(client, account)
    empty = await make_kb(client, account, "Empty")
    url = f"/v1/agents/{agent['id']}/knowledge-bases"
    not_ready = check(await client.put(url, json={"kb_ids": [empty["id"]]}, headers=account.headers))
    assert not_ready.status_code == 422 and not_ready.json()["code"] == "knowledge_base_not_ready"
    unknown = check(await client.put(url, json={"kb_ids": [MISSING_KB]}, headers=account.headers))
    assert unknown.status_code == 422
    too_many = check(
        await client.put(url, json={"kb_ids": [f"kb_{i:026d}" for i in range(11)]}, headers=account.headers)
    )
    assert too_many.status_code == 422
    attached = check(await client.put(url, json={"kb_ids": [kb["id"]]}, headers=account.headers))
    assert [k["id"] for k in attached.json()["knowledge_bases"]] == [kb["id"]]
    assert (
        check(await client.get(url, headers=account.headers)).json()["knowledge_bases"][0]["agent_count"] == 1
    )
    assert (
        check(
            await client.get(f"/v1/agents/{MISSING_AGENT}/knowledge-bases", headers=account.headers)
        ).status_code
        == 404
    )
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    version = (
        await client.get(
            f"/v1/agents/{agent['id']}/versions/{detail['draft_version']['id']}", headers=account.headers
        )
    ).json()
    assert version["config"]["knowledge"] == [
        {"kb_id": kb["id"], "name": "Clinic policies", "description": "Refunds, hours, prices"}
    ]
    in_use = check(await client.delete(f"/v1/knowledge-bases/{kb['id']}", headers=account.headers))
    assert in_use.status_code == 409 and in_use.json()["code"] == "knowledge_base_in_use"
    confirmed = check(
        await client.delete(f"/v1/knowledge-bases/{kb['id']}?confirm=true", headers=account.headers)
    )
    assert confirmed.json()["detached_agent_ids"] == [agent["id"]]


async def test_internal_search(client: httpx.AsyncClient, account: Account, app: FastAPI) -> None:
    from tests.runtime_support import insert_call, owner_sql

    agent = await create_ok(client, account)
    kb = await ready_kb(client, account)
    other = await ready_kb(client, account, "Not attached")
    await client.put(
        f"/v1/agents/{agent['id']}/knowledge-bases", json={"kb_ids": [kb["id"]]}, headers=account.headers
    )
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    call_id = insert_call(account.workspace_id, status="in_progress")
    owner_sql(
        "update calls set agent_id = %s, agent_version_id = %s where id = %s",
        (agent["id"], detail["draft_version"]["id"], call_id),
    )
    service = {"Authorization": f"Bearer {app.state.settings.service_token.get_secret_value()}"}
    body = {"call_id": call_id, "query": "refund within how many days", "kb_ids": [kb["id"]]}
    found = check(await client.post("/v1/internal/knowledge/search", json=body, headers=service))
    assert found.status_code == 200 and found.json()["results"]
    refused = check(
        await client.post(
            "/v1/internal/knowledge/search", json={**body, "kb_ids": [other["id"]]}, headers=service
        )
    )
    assert refused.status_code == 403
    unknown = check(
        await client.post(
            "/v1/internal/knowledge/search",
            json={**body, "call_id": "call_01ARZ3NDEKTSV4RRFFQ69G5FAV"},
            headers=service,
        )
    )
    assert unknown.status_code == 404
    assert (
        await client.post("/v1/internal/knowledge/search", json=body, headers=account.headers)
    ).status_code == 401
    owner_sql("update calls set status = 'ended' where id = %s", (call_id,))  # keep the reaper tests clean
