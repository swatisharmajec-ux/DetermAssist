"""Decision Register read endpoints — Phase 2, owned by DRC."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.forge_auth import get_current_tenant
from app.db import get_db
from app.models import DecisionRegisterEntry, Tenant

router = APIRouter(prefix="/decisions", tags=["decision-register"])


@router.get("/")
def list_decisions(
    release_id: Optional[str] = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    q = db.query(DecisionRegisterEntry).filter(DecisionRegisterEntry.tenant_id == tenant.id)
    if release_id:
        q = q.filter(DecisionRegisterEntry.release_id == release_id)
    return q.order_by(DecisionRegisterEntry.created_at.desc()).all()
