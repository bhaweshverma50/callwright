"""Phone number rows (010 data-model.md section 1). The table is created by migration s010_0001."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def pg_enum(name: str, *values: str) -> ENUM:
    """A Postgres enum created by the migration (never by the ORM)."""
    return ENUM(*values, name=name, create_type=False)


class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    e164: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String(100))
    termination_host: Mapped[str] = mapped_column(String)
    termination_port: Mapped[int | None] = mapped_column(Integer)
    transport: Mapped[str] = mapped_column(
        pg_enum("sip_transport", "auto", "udp", "tcp", "tls"), default="auto"
    )
    auth_username: Mapped[str | None] = mapped_column(String)
    # Name of the 001 secret holding the carrier password; never returned.
    auth_password_secret: Mapped[str | None] = mapped_column(String)
    inbound_allowed_cidrs: Mapped[list[str]] = mapped_column(ARRAY(CIDR), default=list)
    inbound_agent_id: Mapped[str | None] = mapped_column(String)
    outbound_agent_id: Mapped[str | None] = mapped_column(String)
    inbound_webhook_url: Mapped[str | None] = mapped_column(String)
    lk_inbound_trunk_id: Mapped[str | None] = mapped_column(String)
    lk_outbound_trunk_id: Mapped[str | None] = mapped_column(String)
    lk_dispatch_rule_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        pg_enum("channel_status", "provisioning", "active", "error", "draining", "deleted"),
        default="provisioning",
    )
    status_detail: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def termination_address(self) -> str:
        if self.termination_port is None:
            return self.termination_host
        return f"{self.termination_host}:{self.termination_port}"
