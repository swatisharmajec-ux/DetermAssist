"""
Inbound webhook endpoints. Both delegate to the ingestion handlers in
app/ingestion/ — this file is just the HTTP surface. Both are called via
Forge (a Forge function reacting to a Jira/mail event, calling out to this
remote), so both carry the same Forge Invocation Token every other route
does — same tenant resolution, same isolation guarantee.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.forge_auth import get_current_tenant
from app.db import get_db
from app.ingestion.jira_webhook import handle_webhook
from app.ingestion.mail_listener import handle_inbound_email
from app.models import Tenant

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/jira")
async def jira_webhook(
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    payload = await request.json()
    try:
        events = handle_webhook(db, tenant.id, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "events_created": len(events),
        "disruption_event_ids": [e.id for e in events],
    }


@router.post("/mail")
async def mail_webhook(
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    raw_email = await request.json()
    try:
        event = handle_inbound_email(db, tenant.id, raw_email)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"disruption_event_id": event.id, "resolution": event.resolution.value}
