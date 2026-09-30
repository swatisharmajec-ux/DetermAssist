"""
Mail listener — the Exception intake channel (Spec Section 3). Stubbed
until a real inbound provider (SendGrid Inbound Parse / IMAP poll) is
wired; the parsing contract and the write-through logic below are both
real. handle_inbound_email() is what a provider webhook calls once it's
wired up.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models import DisruptionEvent, RecordStatus, ResilienceTraceLogEntry
from app.scoring.resolution_service import apply_pm_resolution


@dataclass
class ExceptionReport:
    jira_issue_key: str
    release_id: str
    reported_by: str
    context: str


def parse_inbound_email(raw_email: dict) -> ExceptionReport:
    """
    Expects a PM-forwarded email tagged with an issue key and release id
    (exact subject-line convention TBD once the provider is wired). This is
    the channel through which off-tool causes — executive direction
    changes, verbal calls — get captured instead of forced into a Jira
    field that was never going to hold them.
    """
    return ExceptionReport(
        jira_issue_key=raw_email.get("issue_key", ""),
        release_id=raw_email.get("release_id", ""),
        reported_by=raw_email.get("from", ""),
        context=raw_email.get("body", ""),
    )


def find_pending_gap(db: Session, tenant_id: str, jira_issue_key: str, release_id: str) -> Optional[DisruptionEvent]:
    """The disruption a forwarded email is meant to explain: a Gap on this
    exact issue and release that's still waiting on a PM, scoped to the
    tenant the email's Forge invocation token resolved to."""
    return (
        db.query(DisruptionEvent)
        .join(ResilienceTraceLogEntry, DisruptionEvent.trace_log_id == ResilienceTraceLogEntry.id)
        .filter(
            DisruptionEvent.tenant_id == tenant_id,
            DisruptionEvent.jira_issue_key == jira_issue_key,
            DisruptionEvent.release_id == release_id,
            ResilienceTraceLogEntry.status == RecordStatus.PROPOSED,
            ResilienceTraceLogEntry.gap_flag == True,  # noqa: E712
        )
        .first()
    )


def handle_inbound_email(db: Session, tenant_id: str, raw_email: dict) -> DisruptionEvent:
    """
    Full path: parse the forwarded email, find the pending Gap it's meant
    to explain, and reclassify it as an Exception through the same
    resolution path a PM clicking "Mark as exception" would use. Raises
    ValueError if there's no matching pending Gap — most likely the email
    arrived for an issue/release that's already been resolved some other
    way, or doesn't match a known Gap at all.
    """
    report = parse_inbound_email(raw_email)
    if not report.jira_issue_key or not report.release_id:
        raise ValueError("email missing issue key or release id — check the subject-line convention")

    event = find_pending_gap(db, tenant_id, report.jira_issue_key, report.release_id)
    if not event:
        raise ValueError(
            f"no pending Gap found for {report.jira_issue_key} / {report.release_id} — "
            "may already be resolved, or the email doesn't match a known disruption"
        )

    return apply_pm_resolution(
        db, tenant_id, event, "reclassify_exception",
        reason=report.context, owner=report.reported_by,
    )
