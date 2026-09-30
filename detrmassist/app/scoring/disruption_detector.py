"""
Layer 2/3 — release-level disruption detection and the Section 2 five-step
gap resolution logic. This is the real implementation behind the
resolve_disruption_stub() contract from the original spec draft.

Unit of flow: an issue's release membership (fix_version) and its position
in an epic -> story chain, tracked at the release level. Sprint membership
is deliberately never inspected here — sprints are too transient to be the
disruption-detection unit (explicit founder decision).
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.models import DisruptionTrigger, Resolution
from app.scoring.classifier import classify_free_text


@dataclass
class FieldDelta:
    field: str
    before: Optional[str]
    after: Optional[str]


_STATUS_ORDER = ["to_do", "in_progress", "in_review", "done"]
_PRIORITY_ORDER = ["blocker", "critical", "major", "minor", "trivial"]


def _normalize(value: Optional[str]) -> Optional[str]:
    """
    Real Jira field values are capitalized with spaces ("To Do", "In
    Progress", "Critical") — the order lists above are lowercase with
    underscores. Without this, every comparison below silently fails
    against real data while still passing against lowercase test
    fixtures, which is exactly the bug a synthetic unit test won't catch
    and a realistic webhook payload will.
    """
    return value.strip().lower().replace(" ", "_") if value else value


def _is_regression(before: Optional[str], after: Optional[str]) -> bool:
    before, after = _normalize(before), _normalize(after)
    if not before or not after or before not in _STATUS_ORDER or after not in _STATUS_ORDER:
        return False
    return _STATUS_ORDER.index(after) < _STATUS_ORDER.index(before)


def _is_downgrade(before: Optional[str], after: Optional[str]) -> bool:
    before, after = _normalize(before), _normalize(after)
    if not before or not after or before not in _PRIORITY_ORDER or after not in _PRIORITY_ORDER:
        return False
    return _PRIORITY_ORDER.index(after) > _PRIORITY_ORDER.index(before)


TRIGGER_RULES = [
    (lambda d: d.field == "fix_version" and d.before and d.after and d.after != d.before,
     DisruptionTrigger.FIX_VERSION_CHANGED),
    (lambda d: d.field == "status" and _is_regression(d.before, d.after),
     DisruptionTrigger.STATUS_REGRESSION),
    (lambda d: d.field == "epic_link" and d.before and not d.after,
     DisruptionTrigger.EPIC_UNLINKED),
    (lambda d: d.field == "blocked" and (d.after or "").lower() == "true",
     DisruptionTrigger.BLOCKED_UNRESOLVED),
    (lambda d: d.field == "priority" and _is_downgrade(d.before, d.after),
     DisruptionTrigger.PRIORITY_DOWNGRADE),
]


def detect_triggers(deltas: List[FieldDelta]) -> List[DisruptionTrigger]:
    """Step 1 — scan a release-level field delta set for disruption triggers."""
    fired = []
    for delta in deltas:
        for predicate, trigger in TRIGGER_RULES:
            if predicate(delta):
                fired.append(trigger)
    return fired


def resolve_disruption(linked_text: Optional[str]) -> Tuple[Resolution, Optional[str]]:
    """
    Steps 2-4 of the Section 2 resolution logic. Takes whatever explanatory
    text the caller already found (a comment, a linked issue's summary —
    the lookup itself is the ingestion layer's job, not this function's)
    and decides the resolution.

    Step 3: explanation found + classifiable D/E/T/R -> CAPTURED_DECISION.
    Step 4: no explanation, or explanation classifies NA -> propose GAP.
    Step 5 (PM confirm / supply reason / reclassify as Exception) happens
    at the API layer — this function only produces the engine's first,
    proposed resolution.
    """
    if not linked_text or not linked_text.strip():
        return Resolution.GAP, None

    result = classify_free_text(linked_text)
    if result.classification == "NA":
        return Resolution.GAP, None

    return Resolution.CAPTURED_DECISION, result.classification
