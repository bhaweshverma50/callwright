"""Sign in with Google (also sign-up), with Google's token endpoint stubbed."""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr

from tests.conftest import PASSWORD, make_client, register, signup, unique_email

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-google-secret"
_ips = itertools.count(1)


def _id_token(claims: dict[str, Any]) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


class Google:
    """A stubbed Google token endpoint; ``respond`` builds the answer from the request form."""

    def __init__(self) -> None:
        self.forms: list[dict[str, str]] = []
        self.respond: Callable[[dict[str, str]], httpx.Response] = lambda form: httpx.Response(500)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://oauth2.googleapis.com/token"
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.forms.append(form)
        return self.respond(form)

    def tokens(self, email: str, **overrides: Any) -> None:
        """Answer with an id_token for ``email``; ``overrides`` replace claims (None drops one)."""
        self.nonce = ""

        def respond(form: dict[str, str]) -> httpx.Response:
            claims: dict[str, Any] = {
                "iss": "https://accounts.google.com",
                "aud": CLIENT_ID,
                "exp": int(time.time()) + 300,
                "nonce": self.nonce,
                "email": email,
                "email_verified": True,
            }
            claims.update(overrides)
            claims = {k: v for k, v in claims.items() if v is not None}
            return httpx.Response(200, json={"id_token": _id_token(claims), "access_token": "ya29.x"})

        self.respond = respond


@pytest_asyncio.fixture
async def google(app: FastAPI) -> AsyncIterator[Google]:
    stub = Google()
    original = app.state.settings
    app.state.settings = original.model_copy(
        update={
            "google_signin_client_id": CLIENT_ID,
            "google_signin_client_secret": SecretStr(CLIENT_SECRET),
        }
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(stub.handler))
    app.state.google_http = http
    try:
        yield stub
    finally:
        app.state.settings = original
        del app.state.google_http
        await http.aclose()


@pytest_asyncio.fixture
async def web(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client with an IP of its own, so per-IP limits never carry over between tests."""
    async with make_client(app, f"10.9.0.{next(_ips)}") as c:
        yield c


async def _start(web: httpx.AsyncClient, google: Google | None = None) -> dict[str, str]:
    response = await web.post("/v1/auth/google/start")
    assert response.status_code == 200, response.text
    query = {k: v[0] for k, v in parse_qs(urlparse(response.json()["authorization_url"]).query).items()}
    if google is not None:
        google.nonce = query["nonce"]
    return query


async def _complete(web: httpx.AsyncClient, state: str, code: str = "auth-code") -> httpx.Response:
    return await web.post("/v1/auth/google/complete", json={"code": code, "state": state})


async def _me(web: httpx.AsyncClient, session: dict[str, Any]) -> dict[str, Any]:
    response = await web.get("/v1/me", headers={"Authorization": f"Bearer {session['access_token']}"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_start_builds_the_authorization_url(
    web: httpx.AsyncClient, google: Google, app: FastAPI
) -> None:
    response = await web.post("/v1/auth/google/start")
    url = urlparse(response.json()["authorization_url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == f"{app.state.settings.web_base_url}/auth/google/callback"
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["prompt"] == "select_account"
    assert query["code_challenge_method"] == "S256"
    ttl = await app.state.redis.ttl(f"auth:google:state:{query['state']}")
    assert 0 < ttl <= 600


async def test_new_user_is_created_with_a_workspace(
    web: httpx.AsyncClient, google: Google, app: FastAPI
) -> None:
    email = unique_email("gnew")
    google.tokens(email)
    query = await _start(web, google)
    response = await _complete(web, query["state"], "the-code")
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["token_type"] == "bearer" and session["expires_in"] > 0
    me = await _me(web, session)
    assert me["user"]["email"] == email and me["user"]["email_verified"] is True
    assert me["workspace"]["id"] and me["balance_usd"] == "5.000000"
    # The code was exchanged with the secret and a verifier that matches the challenge.
    (form,) = google.forms
    assert form["code"] == "the-code" and form["grant_type"] == "authorization_code"
    assert form["client_id"] == CLIENT_ID and form["client_secret"] == CLIENT_SECRET
    assert form["redirect_uri"] == query["redirect_uri"]
    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == query["code_challenge"]
    # No password was ever set, and the session refreshes like any other.
    guess = await web.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    assert guess.status_code == 401
    refreshed = await web.post("/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert refreshed.status_code == 200


async def test_confirmed_user_signs_in_without_a_second_workspace(
    web: httpx.AsyncClient, google: Google, app: FastAPI
) -> None:
    account = await signup(web, app)
    google.tokens(account.email.upper())
    query = await _start(web, google)
    response = await _complete(web, query["state"])
    assert response.status_code == 200, response.text
    me = await _me(web, response.json())
    assert me["user"]["id"] == account.user_id
    assert me["workspace"]["id"] == account.workspace_id
    assert me["balance_usd"] == "5.000000"
    # The password still works: a confirmed account keeps it.
    again = await web.post("/v1/auth/sign-in", json={"email": account.email, "password": PASSWORD})
    assert again.status_code == 200


async def test_unverified_squatter_loses_the_account(
    web: httpx.AsyncClient, google: Google, app: FastAPI
) -> None:
    email = unique_email("squat")
    await register(web, email, "squatter-password-1")
    pending_link = app.state.idp.latest_message(email, "verify_email").token_hash
    google.tokens(email)
    query = await _start(web, google)
    response = await _complete(web, query["state"])
    assert response.status_code == 200, response.text
    me = await _me(web, response.json())
    assert me["user"]["email"] == email and me["workspace"]["id"]
    old = await web.post("/v1/auth/sign-in", json={"email": email, "password": "squatter-password-1"})
    assert old.status_code == 401
    # The verification link the squatter was sent no longer opens the account.
    link = await web.post("/v1/auth/verify-email", json={"token_hash": pending_link})
    assert link.status_code == 400 and link.json()["code"] == "invalid_link"


async def test_squatter_sessions_are_revoked(web: httpx.AsyncClient, google: Google, app: FastAPI) -> None:
    email = unique_email("squat")
    await register(web, email, "squatter-password-1")
    user = await app.state.idp._user_by_email(email)
    stale = (await app.state.idp._new_session(user.id, email)).refresh_token
    google.tokens(email)
    query = await _start(web, google)
    assert (await _complete(web, query["state"])).status_code == 200
    assert (await web.post("/v1/auth/refresh", json={"refresh_token": stale})).status_code == 401


async def test_state_works_once(web: httpx.AsyncClient, google: Google) -> None:
    google.tokens(unique_email("once"))
    query = await _start(web, google)
    assert (await _complete(web, query["state"])).status_code == 200
    replay = await _complete(web, query["state"])
    assert replay.status_code == 400 and replay.json()["code"] == "oauth_state_invalid"
    assert len(google.forms) == 1


async def test_unknown_or_expired_state(web: httpx.AsyncClient, google: Google, app: FastAPI) -> None:
    google.tokens(unique_email("late"))
    unknown = await _complete(web, "never-issued")
    assert unknown.status_code == 400 and unknown.json()["code"] == "oauth_state_invalid"
    query = await _start(web, google)
    await app.state.redis.delete(f"auth:google:state:{query['state']}")  # what the TTL does at 10 minutes
    expired = await _complete(web, query["state"])
    assert expired.status_code == 400 and expired.json()["code"] == "oauth_state_invalid"
    assert google.forms == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "someone-elses-nonce"},
        {"nonce": None},
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 5},
    ],
    ids=["bad-nonce", "no-nonce", "bad-aud", "bad-iss", "expired"],
)
async def test_bad_id_token_claims_are_refused(
    web: httpx.AsyncClient, google: Google, app: FastAPI, overrides: dict[str, Any]
) -> None:
    email = unique_email("badtok")
    google.tokens(email, **overrides)
    query = await _start(web, google)
    response = await _complete(web, query["state"])
    assert response.status_code == 400 and response.json()["code"] == "oauth_state_invalid"
    assert await app.state.idp._user_by_email(email) is None


async def test_both_issuer_spellings_are_accepted(web: httpx.AsyncClient, google: Google) -> None:
    google.tokens(unique_email("iss"), iss="accounts.google.com")
    query = await _start(web, google)
    assert (await _complete(web, query["state"])).status_code == 200


async def test_unverified_google_email_is_refused(
    web: httpx.AsyncClient, google: Google, app: FastAPI
) -> None:
    email = unique_email("unver")
    google.tokens(email, email_verified=False)
    query = await _start(web, google)
    response = await _complete(web, query["state"])
    assert response.status_code == 400 and response.json()["code"] == "google_email_unverified"
    assert await app.state.idp._user_by_email(email) is None


async def test_google_errors_and_timeouts_answer_502(web: httpx.AsyncClient, google: Google) -> None:
    google.respond = lambda form: httpx.Response(503, text="backend error")
    query = await _start(web)
    response = await _complete(web, query["state"])
    assert response.status_code == 502 and response.json()["code"] == "google_unavailable"

    def timeout(form: dict[str, str]) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    google.respond = timeout
    query = await _start(web)
    response = await _complete(web, query["state"])
    assert response.status_code == 502 and response.json()["code"] == "google_unavailable"


async def test_rejected_code_reads_as_an_expired_flow(web: httpx.AsyncClient, google: Google) -> None:
    google.respond = lambda form: httpx.Response(400, json={"error": "invalid_grant"})
    query = await _start(web)
    response = await _complete(web, query["state"])
    assert response.status_code == 400 and response.json()["code"] == "oauth_state_invalid"


async def test_endpoints_are_rate_limited_per_ip(
    web: httpx.AsyncClient, google: Google, app: FastAPI
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"google_signin_rate_limit_per_hour": 2})
    assert (await web.post("/v1/auth/google/start")).status_code == 200
    assert (await web.post("/v1/auth/google/start")).status_code == 200
    limited = await web.post("/v1/auth/google/start")
    assert limited.status_code == 429


async def test_off_without_credentials(web: httpx.AsyncClient, app: FastAPI) -> None:
    assert (await web.get("/v1/auth/config")).json() == {"google_signin": False}
    assert (await web.post("/v1/auth/google/start")).status_code == 404
    assert (await web.post("/v1/auth/google/complete", json={"code": "c", "state": "s"})).status_code == 404


async def test_config_reports_google_signin(web: httpx.AsyncClient, google: Google) -> None:
    assert (await web.get("/v1/auth/config")).json() == {"google_signin": True}
