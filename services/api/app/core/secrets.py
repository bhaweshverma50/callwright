"""Encrypted secrets store (T088) and encrypted configuration values (T084).

Envelope encryption: every value gets its own random 256-bit data key (DEK); the value is sealed
with AES-GCM under the DEK and the DEK is wrapped by a key-encryption key. ``LocalKeyWrapper``
wraps with a master key from ``SECRETS_MASTER_KEY``; a KMS-backed wrapper implements the same
``KeyWrapper`` protocol in production. APIs only ever return ``mask_secret`` output.

CLI: ``python -m app.core.secrets encrypt < value.txt`` prints an ``enc:v1:...`` string for .env.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy import DateTime, LargeBinary, String, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

if TYPE_CHECKING:
    from app.core.config import Settings

_NONCE_BYTES = 12
_ENC_PREFIX = "enc:v1:"


class KeyWrapper(Protocol):
    key_id: str

    def wrap(self, dek: bytes) -> bytes: ...

    def unwrap(self, blob: bytes) -> bytes: ...


class LocalKeyWrapper:
    """Wraps data keys with a 32-byte master key (AES-GCM)."""

    def __init__(self, master_key_b64: str) -> None:
        key = base64.b64decode(master_key_b64)
        if len(key) != 32:
            raise ValueError("SECRETS_MASTER_KEY must be 32 bytes, base64 encoded")
        self._aead = AESGCM(key)
        self.key_id = "local:" + hashlib.sha256(key).hexdigest()[:12]

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, dek, b"dek")

    def unwrap(self, blob: bytes) -> bytes:
        return self._aead.decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], b"dek")


def key_wrapper(settings: Settings) -> KeyWrapper:
    return LocalKeyWrapper(settings.secrets_master_key.get_secret_value())


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    wrapped_dek: bytes
    key_id: str


def seal(plaintext: str, wrapper: KeyWrapper, aad: bytes = b"") -> Sealed:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = nonce + AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return Sealed(ciphertext=ciphertext, wrapped_dek=wrapper.wrap(dek), key_id=wrapper.key_id)


def unseal(sealed: Sealed, wrapper: KeyWrapper, aad: bytes = b"") -> str:
    dek = wrapper.unwrap(sealed.wrapped_dek)
    data = sealed.ciphertext
    return AESGCM(dek).decrypt(data[:_NONCE_BYTES], data[_NONCE_BYTES:], aad).decode("utf-8")


def mask_secret(value: str | None) -> str:
    """Masked form shown by every API: last four characters only when the value is long enough."""
    if not value:
        return ""
    if len(value) < 8:
        return "****"
    return "****" + value[-4:]


def encrypt_config_value(plaintext: str, master_key: SecretStr | str) -> str:
    key = master_key.get_secret_value() if isinstance(master_key, SecretStr) else master_key
    sealed = seal(plaintext, LocalKeyWrapper(key), aad=b"config")
    wrapped = base64.urlsafe_b64encode(sealed.wrapped_dek).decode()
    body = base64.urlsafe_b64encode(sealed.ciphertext).decode()
    return f"{_ENC_PREFIX}{wrapped}:{body}"


def decrypt_config_value(value: str, master_key: SecretStr | str) -> str:
    if not value.startswith(_ENC_PREFIX):
        raise ValueError("not an enc:v1 value")
    key = master_key.get_secret_value() if isinstance(master_key, SecretStr) else master_key
    wrapper = LocalKeyWrapper(key)
    wrapped_b64, _, body_b64 = value[len(_ENC_PREFIX) :].partition(":")
    sealed = Sealed(
        ciphertext=base64.urlsafe_b64decode(body_b64),
        wrapped_dek=base64.urlsafe_b64decode(wrapped_b64),
        key_id=wrapper.key_id,
    )
    return unseal(sealed, wrapper, aad=b"config")


class WorkspaceSecret(Base):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(200))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String)
    masked: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@dataclass(frozen=True)
class SecretRef:
    name: str
    masked: str
    updated_at: datetime


def _aad(workspace_id: str, name: str) -> bytes:
    return f"{workspace_id}/{name}".encode()


async def put_secret(
    session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, name: str, value: str
) -> SecretRef:
    """Create or replace a workspace secret. The session must carry the workspace RLS context."""
    sealed = seal(value, wrapper, aad=_aad(workspace_id, name))
    row = (
        await session.execute(
            select(WorkspaceSecret).where(
                WorkspaceSecret.workspace_id == workspace_id, WorkspaceSecret.name == name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = WorkspaceSecret(workspace_id=workspace_id, name=name)
        session.add(row)
    row.ciphertext = sealed.ciphertext
    row.wrapped_dek = sealed.wrapped_dek
    row.key_id = sealed.key_id
    row.masked = mask_secret(value)
    row.updated_at = datetime.now().astimezone()
    await session.flush()
    return SecretRef(name=name, masked=row.masked, updated_at=row.updated_at)


async def get_secret(session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, name: str) -> str | None:
    row = (
        await session.execute(
            select(WorkspaceSecret).where(
                WorkspaceSecret.workspace_id == workspace_id, WorkspaceSecret.name == name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    sealed = Sealed(ciphertext=row.ciphertext, wrapped_dek=row.wrapped_dek, key_id=row.key_id)
    return unseal(sealed, wrapper, aad=_aad(workspace_id, name))


async def delete_secret(session: AsyncSession, workspace_id: str, name: str) -> bool:
    row = (
        await session.execute(
            select(WorkspaceSecret).where(
                WorkspaceSecret.workspace_id == workspace_id, WorkspaceSecret.name == name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def list_secrets(session: AsyncSession, workspace_id: str) -> list[SecretRef]:
    rows = (
        await session.execute(
            select(WorkspaceSecret)
            .where(WorkspaceSecret.workspace_id == workspace_id)
            .order_by(WorkspaceSecret.name)
        )
    ).scalars()
    return [SecretRef(name=r.name, masked=r.masked, updated_at=r.updated_at) for r in rows]


def _cli(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in {"encrypt", "genkey"}:
        print("usage: python -m app.core.secrets encrypt < plaintext | genkey", file=sys.stderr)
        return 2
    if argv[0] == "genkey":
        print(base64.b64encode(os.urandom(32)).decode())
        return 0
    from app.core.config import get_settings

    plaintext = sys.stdin.read().rstrip("\n")
    print(encrypt_config_value(plaintext, get_settings().secrets_master_key))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
