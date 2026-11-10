"""The foundation migration creates the app roles with a known password only for local ENV."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import get_settings

PATH = Path(__file__).parents[2] / "app/migrations/versions/s001_0001_foundation.py"


def load(monkeypatch: pytest.MonkeyPatch, *, exists: bool, env: str) -> tuple[Any, list[str]]:
    spec = importlib.util.spec_from_file_location("foundation_under_test", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    executed: list[str] = []
    bind = SimpleNamespace(execute=lambda *_a, **_k: SimpleNamespace(first=lambda: (1,) if exists else None))
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: bind, execute=executed.append))
    monkeypatch.setattr(get_settings(), "env", env)
    return module, executed


def test_local_env_creates_the_role_with_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    module, executed = load(monkeypatch, exists=False, env="dev")
    module._role("callwright_app", "APP_DB_PASSWORD", "callwright_app")
    assert len(executed) == 1 and "PASSWORD 'callwright_app'" in executed[0]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_hosted_env_refuses_to_invent_a_password(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    module, executed = load(monkeypatch, exists=False, env=env)
    with pytest.raises(RuntimeError, match="APP_DB_PASSWORD"):
        module._role("callwright_app", "APP_DB_PASSWORD", "callwright_app")
    assert executed == []


def test_hosted_env_uses_the_given_password_and_escapes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "pa'ss")
    module, executed = load(monkeypatch, exists=False, env="prod")
    module._role("callwright_app", "APP_DB_PASSWORD", "callwright_app")
    assert "PASSWORD 'pa''ss'" in executed[0]


def test_existing_role_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    module, executed = load(monkeypatch, exists=True, env="prod")
    module._role("callwright_app", "APP_DB_PASSWORD", "callwright_app")
    assert executed == []
