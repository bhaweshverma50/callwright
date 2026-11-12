"""Versions and failures across syncs (022, PR #1 review): an edited file keeps its document
through repeated edits, versions that could not be taken are tried again, one failing file does
not fail the run, processing failures show on the file and are retried, documents archived before
or while they are processed come back with their real status, and a run that lost its claim or
was cancelled never overwrites the source."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge import jobs as ingest_jobs
from app.knowledge.sources import jobs as sync_jobs
from app.knowledge.sources import sync
from app.knowledge.sources.fake_drive import FakeDriveClient
from app.llms.embeddings.fake import FakeEmbeddings
from tests.conftest import Account
from tests.connector_helpers import (
    connect,
    documents,
    fake_drive,
    make_kb,
    node_id,
    run_of,
    search,
    settle,
    sync_now,
    synced_source,
)
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def _clinic(client: httpx.AsyncClient, account: Account, drive: FakeDriveClient) -> tuple[str, dict]:
    root = drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    return kb_id, await synced_source(client, account, kb_id, conn["id"], root)


async def _rows(app: FastAPI, account: Account, sql: str, **params: Any) -> list[Any]:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        return list((await session.execute(text(sql), params)).all())


async def _file(app: FastAPI, account: Account, source_id: str, name: str) -> Any:
    [row] = await _rows(
        app,
        account,
        "select doc_id, pending_doc_id, state, reason, md5, drive_version from kb_source_files "
        "where source_id = :s and name = :n",
        s=source_id,
        n=name,
    )
    return row


def _named(docs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [d for d in docs if d["display_name"] == name]


async def test_repeated_edits_keep_one_document_and_a_delete_archives_it(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    hours = node_id(fake_drive, "Clinic hours")
    for hour in ("8", "7", "6"):
        fake_drive.edit(hours, [f"The clinic now opens at {hour} am on weekdays and closes at 7 pm."])
        run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
        assert run["counts"]["updated"] == 1 and run["counts"]["added"] == 0 and run["counts"]["skipped"] == 2
        live = _named(await documents(client, account, kb_id), "Clinic hours")
        assert len(live) == 1 and live[0]["status"] == "ready"
        row = await _file(app, account, source["id"], "Clinic hours")
        assert row.doc_id == live[0]["id"] and row.pending_doc_id is None
    assert any("6 am" in r["content"] for r in await search(client, account, kb_id, "clinic opens 6 am"))
    assert not any("7 am" in r["content"] for r in await search(client, account, kb_id, "clinic opens 7 am"))
    quiet = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert quiet["counts"]["unchanged"] == 10 and quiet["counts"]["skipped"] == 2
    fake_drive.delete(hours)
    gone = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert gone["counts"]["archived"] == 1
    assert not _named(await documents(client, account, kb_id), "Clinic hours")
    assert len(_named(await documents(client, account, kb_id, "archived"), "Clinic hours")) == 1


async def test_a_new_version_that_could_not_be_downloaded_is_tried_again(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    parking = node_id(fake_drive, "Parking.pdf")
    before = await _file(app, account, source["id"], "Parking.pdf")
    fake_drive.edit(parking, ["Free parking is now available in the basement for three hours."])
    fake_drive.unavailable.add(parking)
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["counts"]["failed"] == 1 and run["status"] == "succeeded"
    row = await _file(app, account, source["id"], "Parking.pdf")
    assert row.md5 == before.md5 and row.reason == "download_failed"  # markers stay on the served version
    fake_drive.unavailable.clear()
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["counts"]["updated"] == 1 and run["counts"]["failed"] == 0
    row = await _file(app, account, source["id"], "Parking.pdf")
    assert row.md5 != before.md5 and row.reason is None


async def test_one_failing_file_does_not_fail_the_run(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    root = source["root_id"]
    fake_drive.add_doc(root, "Telehealth", ["Video consultations are available every evening."])
    fake_drive.edit(
        node_id(fake_drive, "Insurance"), ["We now also accept Niva Bupa and Care Health insurance cards."]
    )
    fake_drive.flaky.add(node_id(fake_drive, "Insurance"))
    fake_drive.delete(node_id(fake_drive, "Pharmacy.docx"))
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["status"] == "succeeded"
    assert run["counts"]["added"] == 1 and run["counts"]["failed"] == 1 and run["counts"]["archived"] == 1
    [error] = [e for e in run["errors"] if e["state"] == "failed"]
    assert error["name"] == "Insurance" and error["reason"] == "download_failed"


async def test_several_temporary_failures_in_a_row_end_the_run(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    for name in ("Clinic hours", "Insurance", "Lab tests", "Our doctors"):
        fake_drive.edit(node_id(fake_drive, name), [f"{name}: this page was rewritten for the new season."])
        fake_drive.flaky.add(node_id(fake_drive, name))
    fake_drive.delete(node_id(fake_drive, "Pharmacy.docx"))
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["status"] == "failed" and run["failure_reason"] == "google_unavailable"
    assert run["counts"]["archived"] == 0  # removals run last and never ran


async def test_a_transient_processing_failure_shows_on_the_file_and_is_retried(
    client: httpx.AsyncClient,
    app: FastAPI,
    account: Account,
    fake_drive: FakeDriveClient,
    fake_embedder: FakeEmbeddings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    monkeypatch.setattr(ingest_jobs, "BACKOFF_S", ())
    fake_embedder.fail_times = 1
    fake_drive.add_doc(source["root_id"], "Telehealth", ["Video consultations are available every evening."])
    await sync_now(app, source["id"])
    [doc] = _named(await documents(client, account, kb_id), "Telehealth")
    assert doc["status"] == "failed" and doc["error_code"] == "embedding_unavailable"
    row = await _file(app, account, source["id"], "Telehealth")
    assert row.state == "failed" and row.reason == "processing_failed" and row.drive_version is None
    detail = (
        await client.get(f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}", headers=account.headers)
    ).json()
    assert [i["reason"] for i in detail["not_imported"] if i["name"] == "Telehealth"] == ["processing_failed"]
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["counts"]["updated"] == 1
    [doc] = _named(await documents(client, account, kb_id), "Telehealth")
    assert doc["status"] == "ready"
    row = await _file(app, account, source["id"], "Telehealth")
    assert row.state == "synced" and row.reason is None


async def test_a_failed_new_version_is_retried_while_the_old_one_serves(
    client: httpx.AsyncClient,
    app: FastAPI,
    account: Account,
    fake_drive: FakeDriveClient,
    fake_embedder: FakeEmbeddings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    monkeypatch.setattr(ingest_jobs, "BACKOFF_S", ())
    fake_embedder.fail_times = 1
    fake_drive.edit(
        node_id(fake_drive, "Clinic hours"), ["The clinic now opens at 8 am on weekdays and closes at 7 pm."]
    )
    await sync_now(app, source["id"])
    assert any("9 am" in r["content"] for r in await search(client, account, kb_id, "clinic open 9 am"))
    row = await _file(app, account, source["id"], "Clinic hours")
    assert row.pending_doc_id is not None and row.reason == "processing_failed"
    await sync_now(app, source["id"])
    live = _named(await documents(client, account, kb_id), "Clinic hours")
    assert len(live) == 1 and live[0]["status"] == "ready"
    row = await _file(app, account, source["id"], "Clinic hours")
    assert row.doc_id == live[0]["id"] and row.pending_doc_id is None and row.reason is None
    assert any("8 am" in r["content"] for r in await search(client, account, kb_id, "clinic opens 8 am"))


async def test_archived_documents_keep_their_real_status(
    client: httpx.AsyncClient,
    app: FastAPI,
    account: Account,
    fake_drive: FakeDriveClient,
    fake_embedder: FakeEmbeddings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    # Archived while it is processed: it keeps its chunks but stays archived.
    real_embed = fake_embedder.embed

    async def archive_then_embed(texts: list[str]) -> list[list[float]]:
        async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
            await session.execute(
                text(
                    "update kb_documents set status = 'archived', archived_at = now() "
                    "where status = 'processing'"
                )
            )
        return await real_embed(texts)

    monkeypatch.setattr(fake_embedder, "embed", archive_then_embed)
    fake_drive.add_doc(source["root_id"], "Telehealth", ["Video consultations are available every evening."])
    await sync_now(app, source["id"])
    monkeypatch.setattr(fake_embedder, "embed", real_embed)
    [doc] = _named(await documents(client, account, kb_id, "archived"), "Telehealth")
    assert doc["chunk_count"] > 0
    restored = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{doc['id']}/restore", headers=account.headers
    )
    assert restored.status_code == 200 and restored.json()["status"] == "ready"

    # Archived before it was processed: a restore processes it instead of serving nothing.
    [lab] = _named(await documents(client, account, kb_id), "Lab tests")
    await _rows(
        app,
        account,
        "update kb_documents set status = 'archived', archived_at = now(), chunk_count = 0, "
        "processed_at = null where id = :id returning id",
        id=lab["id"],
    )
    restored = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{lab['id']}/restore", headers=account.headers
    )
    assert restored.status_code == 200 and restored.json()["status"] == "uploaded"
    await settle()
    [lab] = _named(await documents(client, account, kb_id), "Lab tests")
    assert lab["status"] == "ready" and lab["chunk_count"] > 0

    # Failed, then archived: it comes back failed, not ready with nothing in it.
    await _rows(
        app,
        account,
        "update kb_documents set status = 'archived', archived_at = now(), error_code = 'internal', "
        "error_message = 'Processing failed.' where id = :id returning id",
        id=lab["id"],
    )
    restored = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{lab['id']}/restore", headers=account.headers
    )
    assert restored.json()["status"] == "failed"


async def test_a_run_taken_over_as_stale_never_touches_the_source(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    _kb_id, source = await _clinic(client, account, fake_drive)
    deps = sync_jobs.deps_from_state(app.state)
    first = await sync.claim(deps.db, account.workspace_id, source["id"], "manual")
    assert first is not None
    await _rows(
        app,
        account,
        "update kb_sources set running_since = now() - interval '11 minutes' where id = :id returning id",
        id=source["id"],
    )
    second = await sync.claim(deps.db, account.workspace_id, source["id"], "manual")
    assert second is not None and second.run_id != first.run_id
    tally = sync.Tally()
    with pytest.raises(sync.Superseded):
        await sync.heartbeat(deps, first, tally, force=True)
    await sync.finish(deps, first, tally, status="failed", failure_reason="internal")
    [(running,)] = await _rows(
        app, account, "select running_run_id from kb_sources where id = :id", id=source["id"]
    )
    assert running == second.run_id  # the stale run did not release the new run's claim
    await sync.heartbeat(deps, second, sync.Tally(), force=True)
    await sync.finish(deps, second, sync.Tally(), status="succeeded")
    [(running, state)] = await _rows(
        app, account, "select running_run_id, state from kb_sources where id = :id", id=source["id"]
    )
    assert running is None and state == "healthy"


async def test_a_cancelled_sync_is_recorded_and_releases_the_source(
    client: httpx.AsyncClient,
    app: FastAPI,
    account: Account,
    fake_drive: FakeDriveClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)

    async def cancelled(*_: Any, **__: Any) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(fake_drive, "list_tree", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await sync.run_sync(sync_jobs.deps_from_state(app.state), source["id"], "manual")
    detail = (
        await client.get(f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}", headers=account.headers)
    ).json()
    assert detail["state"] == "healthy" and detail["last_run"]["status"] == "failed"
    started = await client.post(
        f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}/sync", headers=account.headers
    )
    assert started.status_code == 202
    await settle()


async def test_folder_ids_are_validated_and_synced_files_are_flagged_on_upload(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    folders = await client.get(
        f"/v1/connections/{source['connection_id']}/drive/folders",
        params={"parent": "x' in parents or 'root"},
        headers=account.headers,
    )
    assert folders.status_code == 422
    check = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/check-duplicate",
        json={"file_name": "Parking.pdf", "sha256": "0" * 64, "file_size": 10},
        headers=account.headers,
    )
    assert check.status_code == 200
    [match] = check.json()["matches"]
    assert match["reason"] == "same_name" and match["managed"] is True


def test_the_sync_job_gets_its_own_timeout() -> None:
    from app.worker import job_functions

    [job] = [f for f in job_functions() if f.name == sync_jobs.JOB_NAME]
    assert job.timeout_s == sync_jobs.JOB_TIMEOUT_S
