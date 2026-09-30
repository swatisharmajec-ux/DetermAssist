"""
Resilience Trace Log read + Layer 4 promotion endpoint — Phase 3/4, owned
by WSO (log) and ASD (promotion).
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.forge_auth import get_current_tenant
from app.db import get_db
from app.models import ResilienceTraceLogEntry, Tenant

router = APIRouter(prefix="/trace-log", tags=["resilience-trace-log"])


@router.get("/")
def list_trace_log(
    release_id: Optional[str] = None,
    gap_only: bool = False,
    exception_only: bool = False,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    q = db.query(ResilienceTraceLogEntry).filter(ResilienceTraceLogEntry.tenant_id == tenant.id)
    if release_id:
        q = q.filter(ResilienceTraceLogEntry.release_id == release_id)
    if gap_only:
        q = q.filter(ResilienceTraceLogEntry.gap_flag == True)  # noqa: E712
    if exception_only:
        q = q.filter(ResilienceTraceLogEntry.exception_flag == True)  # noqa: E712
    return q.order_by(ResilienceTraceLogEntry.created_at.desc()).all()


@router.patch("/{entry_id}/promote")
def promote_to_rule(
    entry_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Layer 4 self-healing marker — ASD promoted this Gap's pattern into a
    new rule-layer trigger. This is the write the monthly RTL digest feeds."""
    entry = (
        db.query(ResilienceTraceLogEntry)
        .filter(ResilienceTraceLogEntry.id == entry_id, ResilienceTraceLogEntry.tenant_id == tenant.id)
        .first()
    )
    if not entry:
        raise HTTPException(404, "Trace log entry not found")
    entry.promoted_to_rule = True
    entry.digest_month = entry.digest_month or datetime.utcnow().strftime("%Y-%m")
    db.commit()
    return {"id": entry.id, "promoted_to_rule": entry.promoted_to_rule}
