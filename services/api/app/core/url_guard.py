"""The one test seam for outbound host lookups (003 T089, research R15).

Every outbound request to a customer URL (agent webhooks, channel inbound webhooks, the test
ping, HTTP tool test runs) is checked and sent by ``callwright_contract.url_guard`` with this
``resolver``: tests set it so hosts resolve without DNS; ``None`` uses the system resolver.
"""

from __future__ import annotations

from callwright_contract.url_guard import Resolver

resolver: Resolver | None = None
