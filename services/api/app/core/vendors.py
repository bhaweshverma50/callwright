"""Which vendors the voice worker can run on this deployment (``VOICE_VENDOR_KEYS``).

Shared by admission (calls/components.py), agent validation (agents/vendors.py) and the catalogs
the pickers read (``available``)."""

from __future__ import annotations


def runnable_providers(settings: object) -> frozenset[str] | None:
    """Provider ids the voice worker holds credentials for (``VOICE_VENDOR_KEYS``), or None when
    the deployment does not say (dev, test, offline: no gating)."""
    raw = getattr(settings, "voice_vendor_keys", None)
    ids = frozenset(p.strip().lower() for p in str(raw or "").split(",") if p.strip())
    return ids or None


# The worker runs these without a platform key: noise cancellation off, and Sanas, whose adapter
# passes audio through until its SDK is integrated (worker/adapters/nc/sanas.py).
KEYLESS = frozenset({"none", "sanas"})


def provider_runnable(provider: str, settings: object, listed: frozenset[str] | None) -> bool:
    """Whether the voice worker can run ``provider`` on this deployment.

    Anthropic needs its platform key (003 T069): runnable when the API holds the key (it reads
    the same secret as the worker) or the deployment lists it. Every other provider is runnable
    when gating is off or the deployment lists it. ``azure_openai`` runs on OpenAI when Azure is
    not configured (the worker's fallback), so it follows ``openai`` too."""
    if provider in KEYLESS:
        return True
    if provider == "anthropic":
        return bool(getattr(settings, "anthropic_api_key", None)) or (
            listed is not None and provider in listed
        )
    if listed is None:
        return True
    return provider in listed or (provider == "azure_openai" and "openai" in listed)


def provider_available(provider: str) -> bool:
    """``provider_runnable`` for the running deployment's settings."""
    from app.core.config import get_settings

    settings = get_settings()
    return provider_runnable(provider, settings, runnable_providers(settings))
