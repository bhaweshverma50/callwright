"""Versioned pricing catalog and the launch seed, version 1 (T066, T090, T100).

Seed rates are the reference market rates captured live on 2026-10-16
(research/live/pricing-catalog.json) with Callwright provider and model ids (data-model.md):
one canonical model id per model across providers, platform fee under provider ``callwright``,
noise cancellation as priced $0.0000 rows. ``embedding`` rows price knowledge-base ingestion per
1,000 tokens (unit ``k_tokens``, T090); they are internal and not part of the per-minute call
catalog served by GET /v1/pricing/catalog.

Revision ID: s001_0004
Revises: s001_0003
Create Date: 2026-10-16
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "s001_0004"
down_revision = "s001_0003"
branch_labels = None
depends_on = None

SEED_EFFECTIVE_FROM = "2026-01-01T00:00:00+00:00"
LLM_BUNDLES = [{"unit": "llm_input_tokens", "per_min": 20000}, {"unit": "llm_output_tokens", "per_min": 200}]
TTS_BUNDLES = [{"unit": "tts_chars", "per_min": 750}]

# (component, provider, model, label, rate, bundles, unit)
SEED_V1 = [
    ("stt", "deepgram", None, "Deepgram, Auto", "0.0085", [], "minute"),
    ("stt", "deepgram", "nova-3", "Nova-3", "0.0085", [], "minute"),
    ("stt", "deepgram", "nova-2", "Nova-2", "0.0058", [], "minute"),
    ("stt", "deepgram", "flux-general-en", "Flux", "0.0085", [], "minute"),
    ("stt", "assemblyai", None, "AssemblyAI, Auto", "0.0030", [], "minute"),
    ("stt", "assemblyai", "universal-streaming", "Universal Streaming", "0.0030", [], "minute"),
    ("stt", "assemblyai", "universal-streaming-multilingual", "Universal Streaming Multilingual", "0.0030", [], "minute"),
    ("stt", "sarvam", None, "Sarvam, Auto", "0.0060", [], "minute"),
    ("stt", "sarvam", "saarika:v2.5", "Saarika v2.5", "0.0060", [], "minute"),
    ("stt", "sarvam", "saaras:v3", "Saaras v3", "0.0060", [], "minute"),
    ("llm", "azure_openai", "gpt-5-mini", "GPT-5 Mini", "0.0015", LLM_BUNDLES, "minute"),
    ("llm", "azure_openai", "gpt-5.1", "GPT-5.1", "0.0165", LLM_BUNDLES, "minute"),
    ("llm", "azure_openai", "gpt-5.2", "GPT-5.2", "0.0315", LLM_BUNDLES, "minute"),
    ("llm", "openai", "gpt-5-mini", "GPT-5 Mini", "0.0015", LLM_BUNDLES, "minute"),
    ("llm", "openai", "gpt-5.1", "GPT-5.1", "0.0165", LLM_BUNDLES, "minute"),
    ("llm", "openai", "gpt-5.2", "GPT-5.2", "0.0315", LLM_BUNDLES, "minute"),
    ("tts", "elevenlabs", "eleven_flash_v2_5", "Flash v2.5", "0.0450", TTS_BUNDLES, "minute"),
    ("tts", "elevenlabs", "eleven_flash_v2", "Flash v2", "0.0450", TTS_BUNDLES, "minute"),
    ("tts", "elevenlabs", "eleven_turbo_v2_5", "Turbo v2.5", "0.0450", TTS_BUNDLES, "minute"),
    ("tts", "elevenlabs", "eleven_turbo_v2", "Turbo v2", "0.0450", TTS_BUNDLES, "minute"),
    ("tts", "elevenlabs", "eleven_multilingual_v2", "Multilingual v2", "0.0900", TTS_BUNDLES, "minute"),
    ("tts", "cartesia", "sonic-2", "Sonic 2", "0.0275", TTS_BUNDLES, "minute"),
    ("tts", "cartesia", "sonic-2-2025-03-07", "Sonic 2 (2025-03-07)", "0.0275", TTS_BUNDLES, "minute"),
    ("tts", "cartesia", "sonic-3", "Sonic 3", "0.0275", TTS_BUNDLES, "minute"),
    ("tts", "cartesia", "sonic-turbo", "Sonic Turbo", "0.0275", TTS_BUNDLES, "minute"),
    ("tts", "fishaudio", "s2.1-pro", "S2.1 Pro", "0.0150", TTS_BUNDLES, "minute"),
    ("tts", "fishaudio", "s2-pro", "S2 Pro", "0.0150", TTS_BUNDLES, "minute"),
    ("tts", "fishaudio", "s1", "S1", "0.0150", TTS_BUNDLES, "minute"),
    ("nc", "sanas", "vi", "Voice isolation", "0.0000", [], "minute"),
    ("nc", "sanas", "st", "Standard noise removal", "0.0000", [], "minute"),
    ("nc", "ai_coustics", "standard", "Lightweight noise removal", "0.0000", [], "minute"),
    ("platform", "callwright", None, "Callwright platform fee", "0.0500", [], "minute"),
    # Ingestion embeddings, USD per 1,000 tokens (vendor list price, T090)
    ("embedding", "openai", "text-embedding-3-small", "Text Embedding 3 Small", "0.000020", [], "k_tokens"),
    ("embedding", "azure_openai", "text-embedding-3-small", "Text Embedding 3 Small", "0.000020", [], "k_tokens"),
]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE pricing_catalog_versions (
      version integer PRIMARY KEY CHECK (version >= 1),
      effective_from timestamptz NOT NULL UNIQUE,
      notes text,
      published_by text REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE pricing_rates (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      version integer NOT NULL REFERENCES pricing_catalog_versions(version),
      component text NOT NULL CHECK (component IN ('stt', 'llm', 'tts', 'nc', 'platform', 'embedding')),
      provider text NOT NULL CHECK (provider ~ '^[a-z0-9_]+$'),
      model text,
      label text NOT NULL,
      rate_per_min_usd numeric(18,6) NOT NULL CHECK (rate_per_min_usd >= 0),
      unit text NOT NULL DEFAULT 'minute' CHECK (unit IN ('minute', 'k_tokens')),
      bundles jsonb NOT NULL DEFAULT '[]'::jsonb,
      CONSTRAINT bundles_only_llm_tts CHECK (jsonb_array_length(bundles) = 0 OR component IN ('llm', 'tts')),
      CONSTRAINT unit_matches_component CHECK ((unit = 'k_tokens') = (component = 'embedding'))
    );
    CREATE UNIQUE INDEX uq_pricing_rates_key
      ON pricing_rates (version, component, provider, coalesce(model, ''));
    CREATE UNIQUE INDEX uq_pricing_rates_one_platform
      ON pricing_rates (version) WHERE component = 'platform';
    GRANT SELECT ON pricing_catalog_versions, pricing_rates TO callwright_app;
    GRANT SELECT, INSERT ON pricing_catalog_versions, pricing_rates TO callwright_admin;
    """)
    versions = sa.table(
        "pricing_catalog_versions",
        sa.column("version", sa.Integer),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("notes", sa.Text),
    )
    op.execute(
        versions.insert().values(
            version=1,
            effective_from=sa.text(f"'{SEED_EFFECTIVE_FROM}'::timestamptz"),
            notes="Launch catalog: reference market rates captured 2026-10-16",
        )
    )
    for component, provider, model, label, rate, bundles, unit in SEED_V1:
        op.execute(
            sa.text(
                "INSERT INTO pricing_rates (version, component, provider, model, label, rate_per_min_usd, "
                "unit, bundles) VALUES (1, :component, :provider, :model, :label, CAST(:rate AS numeric), "
                ":unit, CAST(:bundles AS jsonb))"
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
