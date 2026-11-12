"""Knowledge rows (005 data-model.md sections 3 to 5; 022 sources, files and runs). Tables come
from migrations s005_0001 and s022_0001."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIMENSIONS = 1536


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    kb_id: Mapped[str] = mapped_column(String)
    file_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String)
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="uploaded")
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    replaces_doc_id: Mapped[str | None] = mapped_column(String)
    uploaded_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 022: archived documents leave search (it reads only ``ready``) and keep their chunks.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 022: set for documents synced from a source; null for uploads.
    source_id: Mapped[str | None] = mapped_column(String)


class Chunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    kb_id: Mapped[str] = mapped_column(String)
    doc_id: Mapped[str] = mapped_column(String)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeSource(Base):
    """A Drive folder or shared drive feeding one knowledge base (022)."""

    __tablename__ = "kb_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    kb_id: Mapped[str] = mapped_column(String)
    connection_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="google_drive")
    root_kind: Mapped[str] = mapped_column(String)
    root_id: Mapped[str] = mapped_column(String)
    drive_id: Mapped[str | None] = mapped_column(String)
    root_name: Mapped[str] = mapped_column(String)
    include_subfolders: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    state: Mapped[str] = mapped_column(String, default="pending")
    attention_reason: Mapped[str | None] = mapped_column(String)
    held_archive: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    running_run_id: Mapped[str | None] = mapped_column(String)
    running_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceFile(Base):
    """One Drive item a source has seen: imported, skipped or failed (022)."""

    __tablename__ = "kb_source_files"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)
    drive_file_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String, default="")
    mime_type: Mapped[str] = mapped_column(String)
    web_view_link: Mapped[str | None] = mapped_column(String)
    drive_version: Mapped[str | None] = mapped_column(String)
    md5: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String)
    text_sha256: Mapped[str | None] = mapped_column(String)
    doc_id: Mapped[str | None] = mapped_column(String)
    pending_doc_id: Mapped[str | None] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String)
    duplicate_of_doc_id: Mapped[str | None] = mapped_column(String)
    message: Mapped[str | None] = mapped_column(Text)
    last_seen_run_id: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncRun(Base):
    """One sync of a source with its counts and per-file errors (022)."""

    __tablename__ = "kb_sync_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)
    trigger: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    failure_reason: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    renamed: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[int] = mapped_column(Integer, default=0)
    held_back: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    errors_truncated: Mapped[int] = mapped_column(Integer, default=0)
