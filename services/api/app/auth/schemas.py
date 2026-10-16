"""Request and response bodies for /v1/auth (contracts/auth.yaml)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)


class RegisterResponse(BaseModel):
    status: Literal["verification_sent"] = "verification_sent"


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
