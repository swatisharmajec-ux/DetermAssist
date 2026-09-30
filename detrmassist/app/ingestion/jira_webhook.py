"""
Jira webhook intake. parse_changelog() is unchanged and already covered by
tests/test_disruption_detector.py's trigger-detection tests via its output
shape. handle_webhook() is the new piece: it's the full path from a raw
Jira payload to a written DisruptionEvent, going through the same
create_and_resolve_disruption() the API route uses.

Not wired to a live Jira subscription yet — needs a registered webhook
pointed at this endpoint once real Jira OAuth credentials exist. The
parsing and write-through logic below is real and tested against
realistic payload shapes.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import DisruptionEvent, DisruptionTrigger
from app.scoring.disruption_detector import FieldDelta, detect_triggers
from app.scoring.resolution_service import create_and_resolve_disruption

WATCHED_FIELDS = {"fixVersions", "status", "epicLink", "priority", "blocked"}

_FIELD_NAME_MAP = {
    "fixVersions": "fix_version",
    "epicLink": "epic_link",
}


def parse_changelog(payload: dict) -> List[FieldDelta]:
    """Extract watched-field deltas from a Jira changelog webhook payload."""
    deltas = []
    for item in payload.get("changelog", {}).get("items", []):
        field = item.get("field")
        if field not in WATCHED_FIELDS:
            continue
        deltas.append(FieldDelta(
            field=_FIELD_NAME_MAP.get(field, field.lower()),
            before=item.get("fromString"),
            after=item.get("toString"),
        ))
    return deltas


def _current_release(payload: dict) -> Optional[str]:
    """The issue's release right now, per the webhook's issue snapshot."""
    versions = payload.get("issue", {}).get("fields", {}).get("fixVersions") or []
    return versions[0]["name"] if versions else None


def _current_epic(payload: dict) -> Optional[str]:
    epic = payload.get("issue", {}).get("fields", {}).get("epic")
    return epic.get("key") if epic else None


def _latest_comment(payload: dict) -> Optional[str]:
    """
    Section 2 step 2's explanation lookup, MVP version: the most recent
    comment on the issue snapshot the webhook carries. A real explanation
    lookup will eventually also check linked issues — this is the piece
    that's cheap to get right now and covers the common case (someone
    explained the change in a comment on the same ticket).
    """
    comments = payload.get("issue", {}).get("fields", {}).get("comment", {}).get("comments") or []
    return comments[-1]["body"] if comments else None


def _release_for_trigger(trigger: DisruptionTrigger, delta: FieldDelta, current_release: Optional[str]) -> Optional[str]:
    """
    A fix-version-change disrupts the release the issue is leaving, not the
    one it's landing in — so that trigger uses the delta's `before` value.
    Every other trigger uses the issue's current release, since nothing
    about those triggers changed which release the issue belongs to.
    """
    if trigger == DisruptionTrigger.FIX_VERSION_CHANGED:
        return delta.before
    return current_release


def handle_webhook(db: Session, tenant_id: str, payload: dict) -> List[DisruptionEvent]:
    """
    Full path: parse deltas, detect triggers, and write each one through
    the same create/resolve logic the API uses. Returns the events created
    (empty list if nothing watched changed — the common case for most
    webhook deliveries).
    """
    issue_key = payload.get("issue", {}).get("key")
    if not issue_key:
        raise ValueError("payload missing issue.key")

    deltas = parse_changelog(payload)
    current_release = _current_release(payload)
    epic_key = _current_epic(payload)
    explanation = _latest_comment(payload)

    created = []
    for delta in deltas:
        for trigger in detect_triggers([delta]):
            release_id = _release_for_trigger(trigger, delta, current_release)
            if not release_id:
                # No release context at all — can't track this at the
                # release level, so there's nothing to write yet. This
                # shouldn't happen for fix_version_changed (the delta IS
                # the release context) but can for issues with no fix
                # version assigned at all on the other trigger types.
                continue
            event = create_and_resolve_disruption(
                db,
                tenant_id=tenant_id,
                jira_issue_key=issue_key,
                release_id=release_id,
                trigger=trigger,
                epic_key=epic_key,
                field_delta=f"{delta.field}: {delta.before} -> {delta.after}",
                linked_explanation_text=explanation,
            )
            created.append(event)
    return created
