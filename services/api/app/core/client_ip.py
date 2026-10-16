"""The caller's IP address for throttles and rate limits.

Behind a proxy the socket peer is the proxy, and uvicorn's ``--forwarded-allow-ips='*'`` takes
the left-most X-Forwarded-For entry, which the client can forge. With ``TRUSTED_PROXY_HOPS=n``
the address is read ``n`` entries from the right of X-Forwarded-For instead: each trusted proxy
appends the address it saw, so that entry was written by our own outermost proxy.
"""

from __future__ import annotations

from fastapi import Request


def client_ip(request: Request) -> str:
    hops: int = request.app.state.settings.trusted_proxy_hops
    if hops > 0:
        forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
        entries = [e.strip() for e in forwarded.split(",") if e.strip()]
        if entries:
            return entries[-hops] if len(entries) >= hops else entries[0]
    return request.client.host if request.client else "unknown"
