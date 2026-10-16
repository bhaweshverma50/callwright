"""/v1/auth routes (contracts/auth.yaml)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.auth.idp import IdpSession
from app.auth.schemas import (
    EmailRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResetConfirmRequest,
    Session,
    SignInRequest,
    TokenHashRequest,
)
from app.auth.service import AuthService
from app.core.auth import CurrentClaims, bearer_token
from app.core.errors import problem_responses

router = APIRouter(prefix="/auth", tags=["auth"])


def _service(request: Request) -> AuthService:
    state = request.app.state
    return AuthService(state.settings, state.db, state.redis, state.idp)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _session(session: IdpSession) -> Session:
    return Session(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
    )


@router.post(
    "/register", status_code=202, response_model=RegisterResponse, responses=problem_responses(422, 429)
)
async def register(body: RegisterRequest, request: Request) -> RegisterResponse:
    await _service(request).register(body.email, body.password, client_ip(request))
    return RegisterResponse()


@router.post("/verify-email", response_model=Session, responses=problem_responses(400))
async def verify_email(body: TokenHashRequest, request: Request) -> Session:
    return _session(await _service(request).verify_email(body.token_hash))


@router.post(
    "/verify-email/resend", status_code=202, response_class=Response, responses=problem_responses(429)
)
async def resend_verification(body: EmailRequest, request: Request) -> Response:
    await _service(request).resend_verification(body.email, client_ip(request))
    return Response(status_code=202)


@router.post("/sign-in", response_model=Session, responses=problem_responses(401, 403, 429))
async def sign_in(body: SignInRequest, request: Request) -> Session:
    return _session(await _service(request).sign_in(body.email, body.password, client_ip(request)))


@router.post("/refresh", response_model=Session, responses=problem_responses(401))
async def refresh(body: RefreshRequest, request: Request) -> Session:
    return _session(await _service(request).refresh(body.refresh_token))


@router.post("/sign-out", status_code=204, response_class=Response, responses=problem_responses(401))
async def sign_out(request: Request, claims: CurrentClaims) -> Response:
    await _service(request).sign_out(bearer_token(request), claims)
    return Response(status_code=204)


@router.post("/password-reset", status_code=202, response_class=Response, responses=problem_responses(429))
async def request_password_reset(body: EmailRequest, request: Request) -> Response:
    await _service(request).request_password_reset(body.email, client_ip(request))
    return Response(status_code=202)


@router.post(
    "/password-reset/confirm", status_code=204, response_class=Response, responses=problem_responses(400, 422)
)
async def confirm_password_reset(body: ResetConfirmRequest, request: Request) -> Response:
    await _service(request).confirm_password_reset(body.token_hash, body.new_password)
    return Response(status_code=204)
