"""Per-minute rates for the Anthropic Claude models the voice worker can run (003 T069).

A new vendor is one adapter plus one pricing row (Principle I). The rows go into the catalog
version in effect now and any later (scheduled) version, so ``GET /v1/llms/catalog`` prices the
models and admission can quote them. Earlier versions are left alone. No call was ever priced
with these rows: admission refused the provider until this release, so adding them changes no
past quote.

Rate rule: the vendor list price of the per-minute bundle every LLM row carries (20,000 input
and 200 output tokens), so a minute inside the bundle never costs more than it is billed:
Haiku 5.5 at $0.10 / $0.50 per million tokens is $0.0021, Sonnet 5.5 at $2 / $10 is $0.0420.

Revision ID: s003_0004
Revises: s003_0003
Create Date: 2026-11-03
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "s003_0004"
down_revision = "s003_0003"
branch_labels = None
depends_on = None

LLM_BUNDLES = [{"unit": "llm_input_tokens", "per_min": 20000}, {"unit": "llm_output_tokens", "per_min": 200}]

# (component, provider, model, label, rate, bundles, unit), the same shape as s001_0004's SEED_V1.
ROWS = [
    ("llm", "anthropic", "claude-haiku-5-5", "Claude Haiku 5.5", "0.0021", LLM_BUNDLES, "minute"),
    ("llm", "anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", "0.0420", LLM_BUNDLES, "minute"),
]


def upgrade() -> None:
    for component, provider, model, label, rate, bundles, unit in ROWS:
        op.execute(
            sa.text(
                """
                INSERT INTO pricing_rates (version, component, provider, model, label,
                                           rate_per_min_usd, unit, bundles)
                SELECT v.version, :component, :provider, :model, :label, CAST(:rate AS numeric),
                       :unit, CAST(:bundles AS jsonb)
                FROM pricing_catalog_versions v
                WHERE v.effective_from >= coalesce(
                    (SELECT max(effective_from) FROM pricing_catalog_versions
                     WHERE effective_from <= now()),
                    '-infinity'::timestamptz)
                ON CONFLICT DO NOTHING
                """
            ).bindparams(
                component=component,
                provider=provider,
                model=model,
                label=label,
                rate=rate,
                unit=unit,
                bundles=json.dumps(bundles),
            )
        )


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
