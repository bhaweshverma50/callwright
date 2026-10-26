"""Secret header lifecycle (005 T038): encrypt, mask, keep, replace, switch off, delete."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import select

from app.core.secrets import WorkspaceSecret, get_secret
from app.tools import service
from app.tools.schemas import ToolCreate, ToolUpdate
from tests.conftest import make_workspace


def _config(*headers: dict[str, Any]) -> dict[str, Any]:
    return {"url": "https://api.example.com/x", "headers": list(headers)}


async def _secret_names(session: Any) -> set[str]:
    return set((await session.execute(select(WorkspaceSecret.name))).scalars())


async def test_secret_lifecycle(app: FastAPI) -> None:
    user_id, workspace_id = await make_workspace(app)
    actor = service.ToolActor(workspace_id=workspace_id, user_id=user_id)
    wrapper = service.key_wrapper(app.state.settings)
    async with app.state.db.transaction(workspace_id=workspace_id) as session:
        tool = await service.create_tool(
            session,
            actor,
            wrapper,
            ToolCreate(
                type="http",
                name="lookup",
                description="d",
                config=_config({"name": "X-Key", "value": "super-secret-7777", "secret": True}),
            ),
        )
        header = tool.config["headers"][0]
        assert "value" not in header and header["masked_value"] == "****7777"
        ref = header["secret_ref"]
        assert await get_secret(session, wrapper, workspace_id, ref) == "super-secret-7777"
        view = service.tool_view(tool)
        assert "super-secret" not in str(view)

        tool = await service.update_tool(
            session, actor, wrapper, tool.id, ToolUpdate(config=_config({"name": "X-Key", "secret": True}))
        )
        assert tool.config["headers"][0]["secret_ref"] == ref

        tool = await service.update_tool(
            session,
            actor,
            wrapper,
            tool.id,
            ToolUpdate(config=_config({"name": "X-Key", "secret": True, "value": "rotated-8888"})),
        )
        new_ref = tool.config["headers"][0]["secret_ref"]
        assert new_ref != ref and ref not in await _secret_names(session)

        tool = await service.update_tool(
            session,
            actor,
            wrapper,
            tool.id,
            ToolUpdate(config=_config({"name": "X-Key", "secret": False, "value": "plain"})),
        )
        assert tool.config["headers"][0] == {"name": "X-Key", "value": "plain", "secret": False}
        assert new_ref not in await _secret_names(session)

        tool = await service.update_tool(
            session,
            actor,
            wrapper,
            tool.id,
            ToolUpdate(config=_config({"name": "X-Key", "secret": True, "value": "again-9999"})),
        )
        last_ref = tool.config["headers"][0]["secret_ref"]
        copy = await service.duplicate_tool(session, actor, wrapper, tool.id)
        copy_ref = copy.config["headers"][0]["secret_ref"]
        assert (
            copy_ref != last_ref
            and await get_secret(session, wrapper, workspace_id, copy_ref) == "again-9999"
        )
        await service.delete_tool(session, actor, tool.id, force=False)
        names = await _secret_names(session)
        assert last_ref not in names and copy_ref in names
