"""Request and response bodies for /v1/auth (contracts/auth.yaml)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    captcha_token: str | None = Field(default=None, max_length=4096)


class RegisterResponse(BaseModel):
    """202 ``verification_sent``; or 200 ``signed_in`` with tokens when AUTH_AUTO_VERIFY_EMAIL is on."""

    status: Literal["verification_sent", "signed_in"] = "verification_sent"
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: Literal["bearer"] | None = None
    expires_in: int | None = None


class TokenHashRequest(BaseModel):
    token_hash: str = Field(min_length=1)


class EmailRequest(BaseModel):
    email: EmailStr


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ResetConfirmRequest(BaseModel):
    token_hash: str
    new_password: str = Field(min_length=10, max_length=128)


class Session(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
