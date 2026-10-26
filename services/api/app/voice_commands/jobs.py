"""Voice command logs share the 30-day purge with the assistant audit rows (006 T079)."""

from app.analytics_chat.jobs import purge_analytics_audit

__all__ = ["purge_analytics_audit"]
