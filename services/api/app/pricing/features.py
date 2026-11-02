"""Feature-key registry for feature charges and usage reporting (T090, research R14).

A feature key is either a plain key (``prompt_generation``) or ``<prefix>.<name>``
(``eval.intent_fulfillment``). The usage report groups keys into families: the part before the
first dot, with ``eval`` shown as ``evaluations`` and ``simulator`` and ``simulation`` (008) as
``simulations``. Every family
here is listed in the ``FeatureFamily`` enum of specs/001-platform-foundation/contracts/usage.yaml.
"""

from __future__ import annotations

import re

# Plain keys accepted as-is.
PLAIN_KEYS = frozenset(
    {
        "calls",
        "analytics_chat",
        "prompt_generation",
        "post_call_analysis",
        "flow_assistant",
        "voice_copilot",
        "knowledge_ingestion",
        "embedding",
    }
)
# Prefixes that require a ``.<name>`` suffix, mapped to their report family.
PREFIXED_FAMILIES = {
    "eval": "evaluations",
    "simulator": "simulations",
    "simulation": "simulations",
    "issues": "issues",
    "testing": "testing",
}
FAMILIES = frozenset(PLAIN_KEYS | set(PREFIXED_FAMILIES.values()))

_SUFFIX = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def is_valid_feature_key(key: str) -> bool:
    if key in PLAIN_KEYS:
        return True
    prefix, dot, rest = key.partition(".")
    return bool(dot) and prefix in PREFIXED_FAMILIES and bool(_SUFFIX.match(rest))


def feature_family(key: str) -> str:
    """Report family of a registered key; raises ``ValueError`` for an unregistered key."""
    if not is_valid_feature_key(key):
        raise ValueError(f"unregistered feature key {key!r}")
    prefix = key.partition(".")[0]
    return PREFIXED_FAMILIES.get(prefix, prefix)
