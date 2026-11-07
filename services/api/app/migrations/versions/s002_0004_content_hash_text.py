"""Content hashes as text: ``char(64)`` reads back blank-padded, so every reader had to strip it.

The values are unchanged (always 64 hex characters, the CHECK on agent_versions stays).

Revision ID: s002_0004
Revises: s013_0001
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "s002_0004"
down_revision = "s013_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE agent_versions ALTER COLUMN content_hash TYPE text;
    ALTER TABLE templates ALTER COLUMN content_hash TYPE text;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
