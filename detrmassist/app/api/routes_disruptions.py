"""
Disruption lifecycle endpoints — HTTP surface only. The actual create/
resolve logic lives in app/scoring/resolution_service.py, shared with the
Jira webhook and Mail listener ingestion paths.

Every route requires a verified Tenant via get_current_tenant() and every
query filters by it — see app/auth/forge_auth.py for what "verified"
means.

POST /disruptions               — record a fired trigger, engine proposes a
                                    resolution (Section 2 steps 1-4).
PATCH /disruptions/{id}/resolve — PM confirms a Gap, supplies a missing
                                    reason (closing it into a captured
                                    decision), or reclassifies it as an
                                    Exception (Section 2 step 5, Section 3).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.forge_auth import get_current_tenant
from app.db import get_db
from app.models import DisruptionEvent, RecordStatus, ResilienceTraceLogEntry, Tenant
from app.schemas import DisruptionEventCreate, DisruptionResolveRequest
from app.scoring.resolution_service import (
    apply_pm_resolution, create_and_resolve_disruption, get_tenant_disruption,
)

router = APIRouter(prefix="/disruptions", tags=["disruptions"])


@router.get("/")
def list_disruptions(
    release_id: Optional[str] = None,
    needs_review: bool = False,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    needs_review=true returns exactly what the PM review queue shows: proposed
    Gaps that haven't been confirmed, explained, or reclassified yet.
    """
    q = db.query(DisruptionEvent).filter(DisruptionEvent.tenant_id == tenant.id)
    if release_id:
        q = q.filter(DisruptionEvent.release_id == release_id)
    if needs_review:
        q = q.join(ResilienceTraceLogEntry, DisruptionEvent.trace_log_id == ResilienceTraceLogEntry.id).filter(
            ResilienceTraceLogEntry.status == RecordStatus.PROPOSED
        )
    return q.order_by(DisruptionEvent.detected_at.desc()).all()


@router.post("/")
def create_disruption(
    payload: DisruptionEventCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    event = create_and_resolve_disruption(
        db,
        tenant_id=tenant.id,
        jira_issue_key=payload.jira_issue_key,
        release_id=payload.release_id,
        trigger=payload.trigger,
        epic_key=payload.epic_key,
        field_delta=payload.field_delta,
        linked_explanation_text=payload.linked_explanation_text,
    )
    return {"disruption_event_id": event.id, "resolution": event.resolution.value}


@router.patch("/{event_id}/resolve")
def pm_resolve(
    event_id: str,
    payload: DisruptionResolveRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    event = get_tenant_disruption(db, tenant.id, event_id)
    if not event:
        raise HTTPException(404, "Disruption event not found")
    try:
        event = apply_pm_resolution(
            db, tenant.id, event, payload.action,
            reason=payload.reason, owner=payload.owner, classification=payload.classification,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"disruption_event_id": event.id, "resolution": event.resolution.value}
