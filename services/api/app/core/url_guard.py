"""Webhook delivery to a URL the outbound guard checked (003 T089, research R15, FR-040).

``callwright_contract.url_guard.check_url`` vets the URL; ``guarded_request`` then connects to
the checked address with the original ``Host`` header and TLS server name, so DNS rebinding
cannot move the request. Redirects are never followed.

``resolver`` is the one test seam for webhook host lookups (agent webhooks, channel inbound
webhooks, the test ping): tests set it so hosts resolve without DNS; ``None`` uses the system
resolver.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from callwright_contract.url_guard import CheckedUrl, Resolver, host_header, pinned_url

resolver: Resolver | None = None


async def guarded_request(
    client: httpx.AsyncClient,
    method: str,
    checked: CheckedUrl,
    *,
    content: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | httpx.Timeout | None = None,  # noqa: ASYNC109 - per-request httpx timeout
) -> httpx.Response:
    """Send one request to the first checked address of ``checked`` (no redirects)."""
    address = checked.addresses[0]
    request_headers = dict(headers or {})
    request_headers["Host"] = host_header(checked)
    extensions: dict[str, object] = {}
    if checked.scheme == "https":
        extensions["sni_hostname"] = checked.host
    if timeout is not None:
        t = timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
        extensions["timeout"] = t.as_dict()
    request = client.build_request(
        method,
        pinned_url(checked, address),
        content=content,
        headers=request_headers,
        extensions=extensions,
    )
    return await client.send(request, follow_redirects=False)
