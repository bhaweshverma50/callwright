"""Wave 2 integration: foreign keys between calls, agents, agent versions and call costs.

003 (``s003_0001``) and 002 (``s002_0001``) were built in parallel, so ``calls.agent_id``,
``calls.agent_version_id`` and 001's ``call_costs.call_id`` were left without constraints. With
both merged (data-model 003 section 1, 001 ``call_costs``):

* ``calls.agent_id`` references ``agents(id)``;
* ``calls.agent_version_id`` references ``agent_versions(id)``;
* ``call_costs.call_id`` references ``calls(id)``.

All three are ``ON DELETE RESTRICT``: agents are soft-deleted and versions are immutable, and a
priced call keeps its ledger breakdown, so none of these rows may disappear under a call.

Existing orphans (for example ``call_costs`` rows written by the dev usage seeder before calls
existed) stop the upgrade with a message instead of a bare constraint error; reset the dev
database (``make db-reset``) or delete those rows first.

Revision ID: s003_0002
Revises: s002_0003
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "s003_0002"
down_revision = "s002_0003"
branch_labels = None
depends_on = None

_ORPHANS = (
    ("calls", "agent_id", "agents"),
    ("calls", "agent_version_id", "agent_versions"),
    ("call_costs", "call_id", "calls"),
)


def upgrade() -> None:
    checks = "\n".join(
        f"""
      SELECT count(*) INTO n FROM {table} t
        WHERE t.{column} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {target} r WHERE r.id = t.{column});
      IF n > 0 THEN
        RAISE EXCEPTION '% {table} rows reference a missing {target} row through {column}', n
          USING HINT = 'Reset the development database (make db-reset) or delete those rows, then migrate again.';
      END IF;"""
        for table, column, target in _ORPHANS
    )
    op.execute(f"""
    DO $$
    DECLARE n bigint;
    BEGIN{checks}
    END $$;
    """)
    op.execute("""
    ALTER TABLE calls
      ADD CONSTRAINT fk_calls_agent FOREIGN KEY (agent_id)
        REFERENCES agents(id) ON DELETE RESTRICT,
      ADD CONSTRAINT fk_calls_agent_version FOREIGN KEY (agent_version_id)
        REFERENCES agent_versions(id) ON DELETE RESTRICT;
    CREATE INDEX ix_calls_agent_version ON calls (agent_version_id) WHERE agent_version_id IS NOT NULL;
    ALTER TABLE call_costs
      ADD CONSTRAINT fk_call_costs_call FOREIGN KEY (call_id)
        REFERENCES calls(id) ON DELETE RESTRICT;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE call_costs DROP CONSTRAINT fk_call_costs_call;
    DROP INDEX ix_calls_agent_version;
    ALTER TABLE calls
      DROP CONSTRAINT fk_calls_agent_version,
      DROP CONSTRAINT fk_calls_agent;
    """)
