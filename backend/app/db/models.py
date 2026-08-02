"""
SQLAlchemy models for EHR connection and record storage.
Tables are created at startup via Base.metadata.create_all(engine).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """
    Maps Clerk user IDs to patient records.
    Each Clerk user gets a unique patient_id for use across the app.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    clerk_user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EHRConnectionRow(Base):
    __tablename__ = "ehr_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    connection_status: Mapped[str] = mapped_column(String, default="not_connected")
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fhir_resource_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EHRRecordRow(Base):
    __tablename__ = "ehr_records"
    __table_args__ = (
        UniqueConstraint("patient_id", "resource_type", "resource_id", name="uq_ehr_record"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    resource_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISessionRow(Base):
    """
    Persists AI session state between HTTP requests.
    Replaces LangGraph MemorySaver — each row is one active session keyed by UUID.
    Sessions are deleted on completion (confirm / approve).
    """

    __tablename__ = "ai_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # session_id UUID
    session_type: Mapped[str] = mapped_column(String, nullable=False)  # "check_in" | "hypothesis"
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
