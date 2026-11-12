"""Development-only control of the in-memory Google Drive (022 T018; quickstart part A).

Mounted when the dev routes are on and ``CONNECTORS_DRIVE_MODE=fake``; never part of the contract.
``seed`` loads a preset tree, ``change`` edits, renames, moves, deletes, adds and touches files,
``consent`` sets what the next fake consent screen grants, ``revoke`` makes the next token
refresh fail, ``outage`` rate limits every call, ``unshare``
removes access to a root folder, and ``reset`` clears everything.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.knowledge.sources.fake_drive import shared_fake

router = APIRouter(prefix="/dev/fake-drive", tags=["dev"], include_in_schema=False)


class Seed(BaseModel):
    preset: Literal["clinic", "property", "big"]


class Add(BaseModel):
    parent: str
    name: str
    kind: Literal["doc", "pdf", "docx", "sheet"] = "doc"
    text: list[str] = Field(default_factory=lambda: ["New content."])


class Change(BaseModel):
    edits: dict[str, list[str]] = Field(default_factory=dict)
    renames: dict[str, str] = Field(default_factory=dict)
    moves: dict[str, str] = Field(default_factory=dict)
    deletes: list[str] = Field(default_factory=list)
    adds: list[Add] = Field(default_factory=list)
    touch_metadata: list[str] = Field(default_factory=list)
    corrupt: list[str] = Field(default_factory=list)


class Switch(BaseModel):
    on: bool = True


class Unshare(BaseModel):
    root_id: str
    on: bool = True


def _tree() -> dict[str, Any]:
    fake = shared_fake()
    return {
        "nodes": [
            {"id": n.id, "name": n.name, "mime_type": n.mime_type, "parent": n.parent, "version": n.version}
            for n in fake.nodes.values()
            if not n.trashed
        ],
        "shared_drives": fake.shared_drives,
        "revoked": fake.revoked,
        "outage": fake.outage,
        "calls": fake.calls,
    }


@router.get("")
async def show() -> dict[str, Any]:
    return _tree()


@router.post("/seed")
async def seed(body: Seed) -> dict[str, Any]:
    return {"roots": shared_fake().seed(body.preset), **_tree()}


@router.post("/change")
async def change(body: Change) -> dict[str, Any]:
    fake = shared_fake()
    for node_id, text in body.edits.items():
        fake.edit(node_id, text)
    for node_id, name in body.renames.items():
        fake.rename(node_id, name)
    for node_id, parent in body.moves.items():
        fake.move(node_id, parent)
    for node_id in body.deletes:
        fake.delete(node_id)
    for node_id in body.touch_metadata:
        fake.touch(node_id)
    fake.corrupt.update(body.corrupt)
    added = []
    for add in body.adds:
        if add.kind == "doc":
            added.append(fake.add_doc(add.parent, add.name, add.text))
        elif add.kind == "pdf":
            added.append(fake.add_pdf(add.parent, add.name, add.text))
        elif add.kind == "docx":
            added.append(fake.add_docx(add.parent, add.name, add.text))
        else:
            added.append(fake.add_other(add.parent, add.name))
    return {"added": added, **_tree()}


@router.post("/revoke")
async def revoke(body: Switch) -> dict[str, Any]:
    shared_fake().revoked = body.on
    return _tree()


@router.post("/outage")
async def outage(body: Switch) -> dict[str, Any]:
    shared_fake().outage = body.on
    return _tree()


@router.post("/unshare")
async def unshare(body: Unshare) -> dict[str, Any]:
    fake = shared_fake()
    (fake.unshared.add if body.on else fake.unshared.discard)(body.root_id)
    return _tree()


class Consent(BaseModel):
    decline: bool = False
    scopes: list[Literal["drive", "sheets"]] = Field(default_factory=lambda: ["drive", "sheets"])


@router.post("/consent")
async def consent(body: Consent) -> dict[str, Any]:
    """What the next fake Google consent screen grants: decline it, or untick Drive or Sheets."""
    from app.knowledge.sources.drive import SCOPE_DRIVE, SCOPE_SHEETS

    fake = shared_fake()
    fake.consent_decline = body.decline
    granted = {"drive": SCOPE_DRIVE, "sheets": SCOPE_SHEETS}
    fake.granted_scopes = ("openid", "email", *(granted[s] for s in body.scopes))
    return {"decline": fake.consent_decline, "scopes": list(fake.granted_scopes)}


@router.post("/reset")
async def reset() -> dict[str, Any]:
    shared_fake().reset()
    return _tree()
