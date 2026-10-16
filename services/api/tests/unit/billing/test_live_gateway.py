"""Live Stripe gateway request shape against a mocked API (no network)."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs

import httpx
from pydantic import SecretStr

from app.billing.stripe_gateway import FakeStripeGateway, LiveStripeGateway, build_gateway
from tests.conftest import make_settings


async def test_create_checkout_session_form() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/1", "expires_at": 1_800_000_000},
        )

    settings = make_settings(stripe_mode="live", stripe_secret_key=SecretStr("sk_test_123"))
    client = httpx.AsyncClient(base_url="https://api.stripe.com/v1", transport=httpx.MockTransport(handler))
    gateway = LiveStripeGateway(settings, client)
    created = await gateway.create_checkout_session(
        amount_usd=Decimal("25.00"),
        workspace_id="ws_1",
        success_url="https://s",
        cancel_url="https://c",
        idempotency_key="k1",
    )
    assert created.id == "cs_test_1" and created.url.startswith("https://checkout.stripe.com")
    form = {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()}
    assert form["line_items[0][price_data][unit_amount]"] == "2500"
    assert form["metadata[workspace_id]"] == "ws_1"
    assert form["mode"] == "payment"
    assert seen[0].headers["authorization"] == "Bearer sk_test_123"
    assert seen[0].headers["idempotency-key"] == "checkout:ws_1:k1"


def test_build_gateway_modes() -> None:
    assert isinstance(build_gateway(make_settings()), FakeStripeGateway)
    live = make_settings(stripe_mode="live", stripe_secret_key=SecretStr("sk_test_123"))
    assert isinstance(build_gateway(live), LiveStripeGateway)
