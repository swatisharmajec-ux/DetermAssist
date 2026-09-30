"""
The actual create/resolve logic behind disruption handling — extracted out
of the API route so both the HTTP endpoint and the ingestion layer (Jira
webhook, Mail listener) call the exact same path instead of two copies of
the same rules drifting apart from each other.

tenant_id is a required argument everywhere data gets written or looked
up, always sourced from app.auth.forge_auth.get_current_tenant() at the
route layer — never accepted as a value the caller supplies directly.
That's the actual isolation boundary; everything else is bookkeeping.

Raises ValueError on bad input / missing preconditions; the API layer
translates that into HTTPException, the ingestion layer logs and moves on
(a malformed webhook payload shouldn't take the whole endpoint down).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Classification, DecisionRegisterEntry, DisruptionEvent, DisruptionTrigger,
    RecordStatus, ResilienceTraceLogEntry, Resolution, Source,
)
from app.scoring.disruption_detector import resolve_disruption


def get_tenant_disruption(db: Session, tenant_id: str, event_id: str) -> Optional[DisruptionEvent]:
    """The only correct way to fetch a DisruptionEvent by id — scoped to
    the caller's tenant. A plain db.get(DisruptionEvent, event_id) would
    let one tenant read or resolve another tenant's disruption just by
    guessing or enumerating ids."""
    return (
        db.query(DisruptionEvent)
        .filter(DisruptionEvent.id == event_id, DisruptionEvent.tenant_id == tenant_id)
        .first()
    )


def create_and_resolve_disruption(
    db: Session,
    tenant_id: str,
    jira_issue_key: str,
    release_id: str,
    trigger: DisruptionTrigger,
    epic_key: Optional[str] = None,
    field_delta: Optional[str] = None,
    linked_explanation_text: Optional[str] = None,
) -> DisruptionEvent:
    """Section 2 steps 1-4 — record a fired trigger and propose a resolution."""
    event = DisruptionEvent(
        tenant_id=tenant_id,
        jira_issue_key=jira_issue_key,
        release_id=release_id,
        epic_key=epic_key,
        trigger=trigger,
        field_delta=field_delta,
    )
    db.add(event)
    db.flush()

    resolution, classification = resolve_disruption(linked_explanation_text)
    event.resolution = resolution

    if resolution == Resolution.CAPTURED_DECISION:
        dr = DecisionRegisterEntry(
            tenant_id=tenant_id,
            disruption_event_id=event.id,
            jira_issue_key=event.jira_issue_key,
            release_id=event.release_id,
            classification=Classification(classification),
            source=Source.RULE,
            confidence=0.8,
            owner="unassigned",
            context=linked_explanation_text or "",
            rationale=f"Auto-resolved from disruption trigger {event.trigger.value}.",
            status=RecordStatus.PROPOSED,
        )
        db.add(dr)
        db.flush()
        event.decision_register_id = dr.id
    else:
        rtl = ResilienceTraceLogEntry(
            tenant_id=tenant_id,
            disruption_event_id=event.id,
            jira_issue_key=event.jira_issue_key,
            release_id=event.release_id,
            gap_flag=True,
            exception_flag=False,
            status=RecordStatus.PROPOSED,
        )
        db.add(rtl)
        db.flush()
        event.trace_log_id = rtl.id

    db.commit()
    db.refresh(event)
    return event


def apply_pm_resolution(
    db: Session,
    tenant_id: str,
    event: DisruptionEvent,
    action: str,
    reason: Optional[str] = None,
    owner: Optional[str] = None,
    classification: Optional[str] = None,
) -> DisruptionEvent:
    """
    Section 2 step 5 — the three things a proposed Gap can become. Callers
    must fetch `event` via get_tenant_disruption() first, and tenant_id is
    still required here as a second check — defense in depth, not
    decoration, given what this product's own audit trail is for.
    """
    if event.tenant_id != tenant_id:
        raise ValueError("disruption event does not belong to this tenant")

    if action == "confirm_gap":
        if not event.trace_log_entry:
            raise ValueError("No trace log entry to confirm — event did not resolve to a Gap")
        event.trace_log_entry.status = RecordStatus.CONFIRMED
        event.resolution = Resolution.GAP

    elif action == "supply_reason":
        if not classification or not owner:
            raise ValueError("supply_reason requires classification and owner")
        rtl = event.trace_log_entry
        dr = DecisionRegisterEntry(
            tenant_id=tenant_id,
            disruption_event_id=event.id,
            jira_issue_key=event.jira_issue_key,
            release_id=event.release_id,
            classification=Classification(classification),
            source=Source.PM_OVERRIDE,
            confidence=1.0,
            owner=owner,
            context=reason or "",
            rationale=reason or "",
            status=RecordStatus.CONFIRMED,
        )
        db.add(dr)
        db.flush()
        event.decision_register_id = dr.id
        event.resolution = Resolution.CAPTURED_DECISION
        if rtl:
            db.delete(rtl)  # the gap closes — it was never a real gap once explained

    elif action == "reclassify_exception":
        rtl = event.trace_log_entry
        if not rtl:
            raise ValueError("No trace log entry to reclassify")
        rtl.gap_flag = False
        rtl.exception_flag = True
        rtl.exception_context = reason
        rtl.exception_reported_by = owner
        rtl.status = RecordStatus.CONFIRMED
        event.resolution = Resolution.EXCEPTION

    else:
        raise ValueError(f"Unknown action: {action}")

    db.commit()
    return event
