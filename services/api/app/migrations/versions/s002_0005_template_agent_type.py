"""Templates gain an agent type (single prompt or flow) and five more categories.

Existing rows are single-prompt templates, so the column defaults to ``single_prompt``. The
category CHECK is replaced to allow insurance, real estate, hospitality, logistics and utilities.

Revision ID: s002_0005
Revises: s007_0005
Create Date: 2026-11-10
"""

from __future__ import annotations

from alembic import op

revision = "s002_0005"
down_revision = "s007_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE templates
      ADD COLUMN agent_type text NOT NULL DEFAULT 'single_prompt'
      CHECK (agent_type IN ('single_prompt', 'flow'));
    ALTER TABLE templates DROP CONSTRAINT templates_category_check;
    ALTER TABLE templates ADD CONSTRAINT templates_category_check CHECK (category IN (
      'automotive', 'banking', 'ecommerce', 'healthcare', 'telecom',
      'insurance', 'real_estate', 'hospitality', 'logistics', 'utilities'
    ));
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
