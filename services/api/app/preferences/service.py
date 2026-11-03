"""Read and save one user's preferences. The row exists only once something was saved; until
then the defaults apply (onboarding not started)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.auth import Principal
from app.core.db import Database
from app.preferences.schemas import OnboardingOut, OnboardingUpdate, PreferencesOut

_SELECT = text("""
    SELECT onboarding_status, onboarding_step, onboarding_updated_at
    FROM user_preferences WHERE user_id = :uid
""")

# One statement for first save and later saves. Fields not sent keep their value (or the
# column default on insert); :set_step tells "step not sent" apart from "step: null".
_UPSERT = text("""
    INSERT INTO user_preferences AS p
      (user_id, workspace_id, onboarding_status, onboarding_step, onboarding_updated_at)
    VALUES (:uid, :ws, COALESCE(:status, 'not_started'), :step, now())
    ON CONFLICT (user_id) DO UPDATE SET
      onboarding_status = COALESCE(:status, p.onboarding_status),
      onboarding_step = CASE WHEN :set_step THEN :step ELSE p.onboarding_step END,
      onboarding_updated_at = now(),
      updated_at = now()
    RETURNING onboarding_status, onboarding_step, onboarding_updated_at
""")


def _out(row: Any | None) -> PreferencesOut:
    if row is None:
        return PreferencesOut(onboarding=OnboardingOut(status="not_started", step=None, updated_at=None))
    return PreferencesOut(onboarding=OnboardingOut(status=row[0], step=row[1], updated_at=row[2]))


async def get_preferences(db: Database, principal: Principal) -> PreferencesOut:
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        row = (await session.execute(_SELECT, {"uid": principal.user_id})).first()
    return _out(row)


async def update_onboarding(db: Database, principal: Principal, body: OnboardingUpdate) -> PreferencesOut:
    set_step = "step" in body.model_fields_set
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        row = (
            await session.execute(
                _UPSERT,
                {
                    "uid": principal.user_id,
                    "ws": principal.workspace_id,
                    "status": body.status,
                    "step": body.step if set_step else None,
                    "set_step": set_step,
                },
            )
        ).first()
    return _out(row)
