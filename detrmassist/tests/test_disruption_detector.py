"""Section 2 trigger detection and five-step gap resolution logic."""
from app.models import DisruptionTrigger, Resolution
from app.scoring.disruption_detector import FieldDelta, detect_triggers, resolve_disruption


def test_status_regression_detected():
    deltas = [FieldDelta(field="status", before="in_progress", after="to_do")]
    assert DisruptionTrigger.STATUS_REGRESSION in detect_triggers(deltas)


def test_fix_version_change_detected():
    deltas = [FieldDelta(field="fix_version", before="2.4", after="2.5")]
    assert DisruptionTrigger.FIX_VERSION_CHANGED in detect_triggers(deltas)


def test_priority_downgrade_detected():
    deltas = [FieldDelta(field="priority", before="critical", after="minor")]
    assert DisruptionTrigger.PRIORITY_DOWNGRADE in detect_triggers(deltas)


def test_priority_downgrade_detected_with_real_jira_casing():
    # Real Jira sends "Critical" / "Minor", not "critical" / "minor" — this
    # is the exact bug the webhook integration test caught.
    deltas = [FieldDelta(field="priority", before="Critical", after="Minor")]
    assert DisruptionTrigger.PRIORITY_DOWNGRADE in detect_triggers(deltas)


def test_status_regression_detected_with_real_jira_casing():
    deltas = [FieldDelta(field="status", before="In Progress", after="To Do")]
    assert DisruptionTrigger.STATUS_REGRESSION in detect_triggers(deltas)


def test_no_trigger_on_forward_progress():
    deltas = [FieldDelta(field="status", before="to_do", after="in_progress")]
    assert detect_triggers(deltas) == []


def test_unexplained_disruption_proposes_gap():
    resolution, classification = resolve_disruption(None)
    assert resolution == Resolution.GAP
    assert classification is None


def test_explained_disruption_captures_decision():
    resolution, classification = resolve_disruption(
        "We decided to descope this due to a blocked dependency."
    )
    assert resolution == Resolution.CAPTURED_DECISION


def test_unclassifiable_explanation_still_gap():
    # Text is present but carries no DETRM signal — should still be a Gap,
    # not incorrectly captured as a decision.
    resolution, classification = resolve_disruption("Had lunch with the team.")
    assert resolution == Resolution.GAP
