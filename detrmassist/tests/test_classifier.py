"""
Locks in the rule this codebase must never regress on: ambiguous or
signal-free text classifies NA, never D. See spec Section 1 and the
divergence found in the discarded zip.
"""
from app.scoring.classifier import classify_free_text_fast, classify_structured_field


def test_no_signal_defaults_to_na_not_decision():
    result = classify_free_text_fast("Had lunch with the team, nice weather today.")
    assert result.classification == "NA"


def test_empty_field_is_na_full_confidence():
    result = classify_free_text_fast("")
    assert result.classification == "NA"
    assert result.confidence == 1.0


def test_decision_marker_detected():
    result = classify_free_text_fast("We decided to go with option B for the release.")
    assert result.classification == "D"


def test_enforcement_marker_detected():
    result = classify_free_text_fast("This requires approval per policy before merging.")
    assert result.classification == "E"


def test_structured_field_unmapped_is_na():
    result = classify_structured_field("assignee", "jdoe")
    assert result.classification == "NA"


def test_structured_field_mapped():
    result = classify_structured_field("priority", "high")
    assert result.classification == "E"
    assert result.confidence == 1.0
