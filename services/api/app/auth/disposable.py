"""Throwaway email domains refused at registration (BLOCK_DISPOSABLE_EMAIL, EXTRA_BLOCKED_EMAIL_DOMAINS).

The list is the CC0 disposable-email-domains project, refreshed by scripts/update_disposable_domains.sh.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import Settings
from app.core.errors import ProblemError

LIST_PATH = Path(__file__).with_name("disposable_domains.txt")


@lru_cache(maxsize=1)
def _blocklist() -> frozenset[str]:
    lines = LIST_PATH.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip() and not line.startswith("#"))


def is_blocked_domain(domain: str, extra: frozenset[str] = frozenset(), *, use_list: bool = True) -> bool:
    """True when the domain or any parent domain is listed (mail.tempmail.com matches tempmail.com)."""
    labels = domain.strip().lower().rstrip(".").split(".")
    blocked = _blocklist() if use_list else frozenset()
    return any(
        ".".join(labels[i:]) in blocked or ".".join(labels[i:]) in extra for i in range(len(labels) - 1)
    )


def check_email_allowed(settings: Settings, email: str) -> None:
    extra = frozenset(d.strip().lower() for d in settings.extra_blocked_email_domains if d.strip())
    if not settings.block_disposable_email and not extra:
        return
    domain = email.rpartition("@")[2]
    if is_blocked_domain(domain, extra, use_list=settings.block_disposable_email):
        raise ProblemError(
            400,
            "email_not_allowed",
            "Email address not allowed",
            "Temporary email addresses can't be used. Sign up with a work or personal email address.",
        )
