"""
AI Session Store
----------------
Replaces LangGraph MemorySaver + StateGraph graph-level checkpointing.

Sessions are persisted to the `ai_sessions` SQLite/PostgreSQL table so they
survive server restarts.  Each session is identified by a UUID string that
the router generates at `/start` and passes back to the client.

Public API
----------
get(session_id)          → dict | None
save(session_id, type, state)  → None   (upsert)
delete(session_id)       → None
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.db.models import AISessionRow
from app.db.session import get_session

logger = logging.getLogger(__name__)


def get(session_id: str) -> dict[str, Any] | None:
    """Return the stored state dict, or None if the session does not exist."""
    with get_session() as db:
        row = db.get(AISessionRow, session_id)
        return dict(row.state_json) if row else None


def save(session_id: str, session_type: str, state: dict[str, Any]) -> None:
    """Upsert session state.  `session_type` is only written on creation."""
    with get_session() as db:
        row = db.get(AISessionRow, session_id)
        if row:
            row.state_json = state
            # flag_modified forces SQLAlchemy to include the JSON column in the
            # UPDATE even when its content changed but the reference stayed the same.
            flag_modified(row, "state_json")
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = AISessionRow(
                id=session_id,
                session_type=session_type,
                state_json=state,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(row)
        db.commit()
    logger.info("session_store.save: %s status=%s", session_id, state.get("status"))


def delete(session_id: str) -> None:
    """Delete a completed session.  No-op if already absent."""
    with get_session() as db:
        row = db.get(AISessionRow, session_id)
        if row:
            db.delete(row)
            db.commit()
    logger.debug("session_store.delete: %s", session_id)


def list_for_patient(patient_id: str, session_type: str) -> list[dict[str, Any]]:
    """
    Return all sessions of `session_type` for the given patient, newest first.

    Patient identity is stored inside state_json (no dedicated column), so we
    load all rows of the requested type and filter in Python.  This is fine for
    the expected volume (tens of sessions per patient, not millions).

    Each returned dict contains:
        session_id, status, created_at, updated_at
    plus any extra fields present in state_json (observation_count, etc.).
    """
    with get_session() as db:
        rows = (
            db.query(AISessionRow)
            .filter(AISessionRow.session_type == session_type)
            .order_by(AISessionRow.created_at.desc())
            .all()
        )
    results = []
    for row in rows:
        state = row.state_json or {}
        if state.get("patient_id") != patient_id:
            continue
        results.append({
            "session_id": row.id,
            "session_type": row.session_type,
            "status": state.get("status", "unknown"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            # Include lightweight summary fields — avoid returning full state_json
            "observation_count": state.get("observation_count", 0),
            "hypothesis_count": len((state.get("hypothesis_report") or {}).get("hypotheses", [])),
            "human_approved": state.get("human_approved", False),
            "errors": state.get("errors", []),
        })
    return results
