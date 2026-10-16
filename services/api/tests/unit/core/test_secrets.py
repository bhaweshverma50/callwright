"""Encrypted secrets store and encrypted config values (T088, T084, Principle V)."""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import Settings
from app.core.secrets import (
    LocalKeyWrapper,
    Sealed,
    decrypt_config_value,
    delete_secret,
    encrypt_config_value,
    get_secret,
    list_secrets,
    mask_secret,
    put_secret,
    seal,
    unseal,
)
from tests.conftest import make_settings, make_workspace

KEY = base64.b64encode(os.urandom(32)).decode()


def test_seal_round_trip_with_fresh_data_keys() -> None:
    wrapper = LocalKeyWrapper(KEY)
    a, b = seal("value", wrapper), seal("value", wrapper)
    assert a.ciphertext != b.ciphertext and a.wrapped_dek != b.wrapped_dek
    assert unseal(a, wrapper) == "value"
    assert b"value" not in a.ciphertext


def test_wrong_master_key_or_aad_fails() -> None:
    sealed = seal("value", LocalKeyWrapper(KEY), aad=b"ws_1/name")
    with pytest.raises(InvalidTag):
        unseal(sealed, LocalKeyWrapper(base64.b64encode(os.urandom(32)).decode()), aad=b"ws_1/name")
    with pytest.raises(InvalidTag):
        unseal(sealed, LocalKeyWrapper(KEY), aad=b"ws_2/name")
    tampered = Sealed(sealed.ciphertext[:-1] + b"x", sealed.wrapped_dek, sealed.key_id)
    with pytest.raises(InvalidTag):
        unseal(tampered, LocalKeyWrapper(KEY), aad=b"ws_1/name")


def test_master_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError):
        LocalKeyWrapper(base64.b64encode(b"short").decode())


@pytest.mark.parametrize(
    ("value", "masked"),
    [(None, ""), ("", ""), ("abc", "****"), ("sk_live_1234567890abcd", "****abcd")],
)
def test_mask(value: str | None, masked: str) -> None:
    assert mask_secret(value) == masked


def test_encrypted_config_values_are_decrypted_at_load() -> None:
    token = encrypt_config_value("whsec_real_secret", KEY)
    assert token.startswith("enc:v1:")
    assert decrypt_config_value(token, KEY) == "whsec_real_secret"
    settings = make_settings(secrets_master_key=SecretStr(KEY), stripe_webhook_secret=SecretStr(token))
    assert settings.stripe_webhook_secret.get_secret_value() == "whsec_real_secret"
    assert "whsec_real_secret" not in repr(settings)


def test_production_refuses_dev_defaults() -> None:
    with pytest.raises(ValueError, match="dev defaults"):
        Settings(_env_file=None, env="prod")  # type: ignore[call-arg]


async def test_workspace_secret_store(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    wrapper = LocalKeyWrapper(app.state.settings.secrets_master_key.get_secret_value())
    async with app.state.db.transaction(workspace_id=ws) as session:
        ref = await put_secret(session, wrapper, ws, "sip_password", "super-secret-value")
        assert ref.masked == "****alue"
        stored = (
            await session.execute(text("select ciphertext from secrets where name = 'sip_password'"))
        ).scalar()
        assert b"super-secret-value" not in stored
        assert await get_secret(session, wrapper, ws, "sip_password") == "super-secret-value"
        await put_secret(session, wrapper, ws, "sip_password", "rotated-value-9")
        assert await get_secret(session, wrapper, ws, "sip_password") == "rotated-value-9"
        assert [s.name for s in await list_secrets(session, ws)] == ["sip_password"]
        assert await delete_secret(session, ws, "sip_password") is True
        assert await get_secret(session, wrapper, ws, "sip_password") is None
