"""Platform agent templates (002 T071, research R16).

Global table without RLS: the app role only reads it; the sync job
(``python -m app.templates.jobs sync``) writes it as the admin role from
``app/templates/seed/*.yaml``.

Revision ID: s002_0002
Revises: s002_0001
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s002_0002"
down_revision = "s002_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE templates (
      id text PRIMARY KEY CHECK (id ~ '^[a-z0-9-]{3,64}$'),
      category text NOT NULL CHECK (category IN ('automotive', 'banking', 'ecommerce', 'healthcare', 'telecom')),
      name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
      description text NOT NULL CHECK (char_length(description) <= 300),
      icon text NOT NULL,
      direction text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
      config jsonb NOT NULL,
      sort_order integer NOT NULL DEFAULT 0,
      is_active boolean NOT NULL DEFAULT true,
      content_hash char(64) NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_templates_active_sort ON templates (sort_order, id) WHERE is_active;
    GRANT SELECT ON templates TO callwright_app;
    GRANT SELECT, INSERT, UPDATE ON templates TO callwright_admin;
    """)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
