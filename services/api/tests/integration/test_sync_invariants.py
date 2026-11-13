"""Sync invariants over many syncs (022 data-model.md "Invariants", PR #1 review).

Every earlier test checks one sync after a change, which is how the first-edit bug slipped
through. This test drives random sequences of Drive changes (edit, rename, move inside and out of
the folder, delete, add, metadata-only touches), restores from the Archived tab and revoked-access
syncs across 8 syncs per seed, drains ingestion after each, and checks I1 to I6 every time.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources.fake_drive import GOOGLE_DOC, FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import (
    complete,
    connect,
    fake_drive,
    make_kb,
    settle,
    start,
    sync_now,
    synced_source,
)
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]

SYNCS = 8
ARCHIVED = "select id from kb_documents where kb_id = :k and status = 'archived'"


@dataclass
class World:
    app: FastAPI
    client: httpx.AsyncClient
    account: Account
    drive: FakeDriveClient
    kb_id: str
    source_id: str
    root: str
    sub: str
    outside: str


async def _q(w: World, sql: str, **params: Any) -> list[Any]:
    async with w.app.state.db.transaction(workspace_id=w.account.workspace_id) as session:
        return list((await session.execute(text(sql), params)).all())


async def _snapshot(w: World) -> tuple[list[Any], list[Any]]:
    docs = await _q(
        w, "select id, status, sha256, display_name from kb_documents where kb_id = :k order by id", k=w.kb_id
    )
    files = await _q(
        w,
        "select drive_file_id, doc_id, pending_doc_id, state, md5, drive_version, name, path "
        "from kb_source_files where source_id = :s order by drive_file_id",
        s=w.source_id,
    )
    return docs, files


def _listed(w: World) -> dict[str, Any]:
    """Supported files the source can see, as the fake Drive would list them."""
    inside = {w.root, w.sub}
    return {
        n.id: n
        for n in w.drive.nodes.values()
        if not n.trashed
        and n.parent in inside
        and n.mime_type in (GOOGLE_DOC, *SUPPORTED_BINARY)
        and not n.size_override
    }


SUPPORTED_BINARY = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)


async def _check(w: World, restored: set[str], archived_before: set[str]) -> None:
    rows = await _q(
        w,
        "select f.drive_file_id, f.doc_id, f.pending_doc_id, f.state, f.md5, f.drive_version, f.sha256 "
        "from kb_source_files f where f.source_id = :s",
        s=w.source_id,
    )
    docs = {
        r.id: r
        for r in await _q(
            w,
            "select id, status, sha256, source_id, chunk_count from kb_documents where kb_id = :k",
            k=w.kb_id,
        )
    }
    live_managed = {i for i, d in docs.items() if d.source_id == w.source_id and d.status != "archived"}

    # I1: every live managed document is pointed at by exactly one source file.
    pointers: dict[str, int] = {}
    for r in rows:
        for doc_id in (r.doc_id, r.pending_doc_id):
            if doc_id:
                pointers[doc_id] = pointers.get(doc_id, 0) + 1
    for doc_id in live_managed:
        assert pointers.get(doc_id) == 1, f"I1: {doc_id} has {pointers.get(doc_id, 0)} source files"

    # I2: at most one live version per Drive file, and none pending once ingestion drained.
    for r in rows:
        assert r.pending_doc_id is None, f"I2: {r.drive_file_id} still has a pending version"
        live = [d for d in (r.doc_id,) if d in live_managed]
        assert len(live) <= 1
    assert all(docs[d].status == "ready" and docs[d].chunk_count for d in live_managed), (
        "I2: live doc not ready"
    )

    # I3: a served file's markers and hash are those of the version actually served.
    listed = _listed(w)
    for r in rows:
        if r.state != "synced" or r.doc_id is None:
            continue
        node = listed.get(r.drive_file_id)
        assert node is not None, f"I3: {r.drive_file_id} synced but not listed"
        # Google Docs change by version; PDF and Word files by content (a touch moves only the version).
        if node.mime_type == GOOGLE_DOC:
            assert r.drive_version == str(node.version), f"I3: {r.drive_file_id} markers behind Drive"
        else:
            expected = hashlib.md5(node.content).hexdigest()  # noqa: S324
            assert r.md5 == expected, f"I3: {r.drive_file_id} markers behind Drive"
        assert docs[r.doc_id].sha256 == r.sha256, f"I3: {r.drive_file_id} hash is not the served version's"
    # Every listed supported file is served.
    served = {r.drive_file_id for r in rows if r.doc_id in live_managed}
    assert set(listed) <= served, f"I3: listed but not served: {set(listed) - served}"

    # I4: no sync holds the source once everything settled, and one running run at most.
    [(running,)] = await _q(w, "select running_run_id from kb_sources where id = :s", s=w.source_id)
    assert running is None, "I4: claim not released"
    [(open_runs,)] = await _q(
        w, "select count(*) from kb_sync_runs where source_id = :s and status = 'running'", s=w.source_id
    )
    assert open_runs == 0

    # I5: an archived document comes back only through restore or its file returning.
    back = archived_before & live_managed
    for doc_id in back:
        row = next((r for r in rows if r.doc_id == doc_id), None)
        assert doc_id in restored or (row is not None and row.drive_file_id in listed), (
            f"I5: {doc_id} revived"
        )


async def _restore_one(w: World, rng: random.Random) -> str | None:
    archived = [
        r.id
        for r in await _q(
            w, "select id from kb_documents where kb_id = :k and status = 'archived'", k=w.kb_id
        )
    ]
    if not archived:
        return None
    doc_id = rng.choice(sorted(archived))
    response = await w.client.post(
        f"/v1/knowledge-bases/{w.kb_id}/documents/{doc_id}/restore", headers=w.account.headers
    )
    assert response.status_code == 200, response.text
    return doc_id


def _change(w: World, rng: random.Random, step: int) -> None:
    files = sorted(_listed(w))
    words = f"Revision {step}-{rng.randint(0, 10**6)}: the clinic policy text was rewritten for this season."
    removed = False
    for _ in range(rng.randint(1, 3)):
        op = rng.choice(["edit", "edit", "rename", "move_in", "touch", "add", "delete", "move_out"])
        if not files and op != "add":
            op = "add"
        target = rng.choice(files) if files else None
        if op in ("delete", "move_out") and removed:
            op = "edit"  # one removal per sync keeps clear of the mass-archive guard
        if op == "edit" and target:
            w.drive.edit(target, [words])
        elif op == "rename" and target:
            w.drive.rename(target, f"{w.drive.nodes[target].name.split(' v')[0]} v{step}")
        elif op == "move_in" and target:
            w.drive.move(target, w.sub if w.drive.nodes[target].parent == w.root else w.root)
        elif op == "touch" and target:
            w.drive.touch(target)
        elif op == "add":
            w.drive.add_doc(w.root, f"Note {step}-{rng.randint(0, 999)}", [words])
        elif op == "delete" and target:
            w.drive.delete(target)
            removed = True
        elif op == "move_out" and target:
            w.drive.move(target, w.outside)
            removed = True
        files = sorted(_listed(w))


@pytest.mark.parametrize("seed", range(1, 13))
async def test_invariants_hold_across_random_syncs(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient, seed: int
) -> None:
    rng = random.Random(seed)
    root = fake_drive.seed("clinic")["Clinic policies"]
    sub = next(n.id for n in fake_drive.nodes.values() if n.name == "2026")
    outside = fake_drive.add_folder("Elsewhere")
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    w = World(app, client, account, fake_drive, kb_id, source["id"], root, sub, outside)
    restored: set[str] = set()
    await _check(w, restored, set())
    for step in range(1, SYNCS + 1):
        archived_before = {
            r.id
            for r in await _q(
                w, "select id from kb_documents where kb_id = :k and status = 'archived'", k=kb_id
            )
        }
        roll = rng.random()
        if roll < 0.15:
            # I6: a failed run (revoked access) changes nothing.
            _change(w, rng, step)
            before = await _snapshot(w)
            fake_drive.revoked = True
            await sync_now(app, w.source_id)
            assert await _snapshot(w) == before, "I6: a failed run changed something"
            fake_drive.revoked = False
            healed = await complete(client, account, await start(client, account, conn["id"]))
            assert healed.status_code == 200, healed.text
            await settle()
        elif roll < 0.3:
            doc_id = await _restore_one(w, rng)
            if doc_id:
                restored.add(doc_id)
            await settle()
        _change(w, rng, step)
        await sync_now(app, w.source_id)
        await _check(w, restored, archived_before)
