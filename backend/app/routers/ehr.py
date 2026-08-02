"""
EHR Router — /ehr
-----------------
Patient Access connection flow (Medblocks hosted page):

  POST /ehr/connect/start    → returns auth_url for Medblocks redirect
  POST /ehr/connect/complete → verifies session + checks connection status
  POST /ehr/sync             → paginated FHIR record pull + upsert into DB
  GET  /ehr/status           → current EHR connection state for patient
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from app.db.session import get_session
from app.db.models import EHRConnectionRow, EHRRecordRow
from app.models.hypothesis import (
    CompleteEHRConnectionRequest,
    EHRConnection,
    StartEHRConnectionRequest,
    StartEHRConnectionResponse,
    SyncEHRRequest,
    SyncEHRResponse,
)
from app.services.ehr_reader import (
    get_connections,
    pull_fhir_records,
    start_patient_session,
    verify_patient_session,
    _active_connection_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ehr", tags=["EHR Connection"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_connection(session, patient_id: str) -> EHRConnectionRow:
    row = session.query(EHRConnectionRow).filter_by(patient_id=patient_id).first()
    if not row:
        row = EHRConnectionRow(patient_id=patient_id)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/connect/start", response_model=StartEHRConnectionResponse)
async def start_ehr_connection(body: StartEHRConnectionRequest) -> StartEHRConnectionResponse:
    """Start Medblocks patient session. Returns auth_url to redirect patient."""
    try:
        auth_url = await start_patient_session(body.patient_id, body.return_url)
    except Exception as exc:
        logger.error("start_patient_session failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Medblocks session start failed: {exc}") from exc

    with get_session() as session:
        row = _get_or_create_connection(session, body.patient_id)
        row.connection_status = "pending"
        session.commit()

    return StartEHRConnectionResponse(auth_url=auth_url)


@router.post("/connect/complete", response_model=EHRConnection)
async def complete_ehr_connection(body: CompleteEHRConnectionRequest) -> EHRConnection:
    """
    Verify the Medblocks patient session server-side after OAuth return.
    Update connection status based on active connections.
    """
    try:
        await verify_patient_session(body.patient_session_id)
        connections = await get_connections(body.patient_id)
    except Exception as exc:
        logger.error("complete_ehr_connection failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Medblocks verification failed: {exc}") from exc

    status = _active_connection_status(connections)
    now = datetime.now(timezone.utc)

    with get_session() as session:
        row = _get_or_create_connection(session, body.patient_id)
        row.connection_status = status
        if status == "active":
            row.connected_at = now
        session.commit()

    return EHRConnection(
        patient_id=body.patient_id,
        connection_status=status,
        connected_at=now if status == "active" else None,
    )


@router.post("/sync", response_model=SyncEHRResponse)
async def sync_ehr_records(body: SyncEHRRequest) -> SyncEHRResponse:
    """
    Pull FHIR records from Medblocks and upsert into the local DB.
    Records may not be available immediately after connection.
    """
    try:
        records_by_type = await pull_fhir_records(body.patient_id)
    except Exception as exc:
        logger.error("pull_fhir_records failed for %s: %s", body.patient_id, exc)
        raise HTTPException(status_code=502, detail=f"FHIR record pull failed: {exc}") from exc

    synced_counts: dict[str, int] = {}
    now = datetime.now(timezone.utc)

    with get_session() as session:
        for resource_type, resources in records_by_type.items():
            count = 0
            for resource in resources:
                resource_id = resource.get("id", "")
                if not resource_id:
                    continue
                # Upsert — idempotent by (patient_id, resource_type, resource_id)
                stmt = (
                    sqlite_upsert(EHRRecordRow)
                    .values(
                        patient_id=body.patient_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        resource_json=resource,
                        synced_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["patient_id", "resource_type", "resource_id"],
                        set_={"resource_json": resource, "synced_at": now},
                    )
                )
                session.execute(stmt)
                count += 1
            synced_counts[resource_type] = count

        # Update connection metadata
        row = _get_or_create_connection(session, body.patient_id)
        row.fhir_resource_counts = synced_counts
        row.last_synced_at = now
        session.commit()

    logger.info("EHR sync complete for %s: %s", body.patient_id, synced_counts)
    return SyncEHRResponse(patient_id=body.patient_id, synced_counts=synced_counts)


@router.get("/status", response_model=EHRConnection)
def get_ehr_status(patient_id: str) -> EHRConnection:
    """Return current EHR connection state for a patient."""
    with get_session() as session:
        row = session.query(EHRConnectionRow).filter_by(patient_id=patient_id).first()
        if not row:
            return EHRConnection(patient_id=patient_id)
        return EHRConnection(
            patient_id=row.patient_id,
            connection_status=row.connection_status,
            connected_at=row.connected_at,
            fhir_resource_counts=row.fhir_resource_counts or {},
            last_synced_at=row.last_synced_at,
        )
