"""Locks in the two hard invariants from Spec Section 5."""
import pytest

from app.models import Classification, ResilienceTraceLogEntry, DecisionRegisterEntry, Source


def test_gap_and_exception_mutually_exclusive():
    with pytest.raises(ValueError):
        ResilienceTraceLogEntry(
            jira_issue_key="ABC-1",
            release_id="2.5",
            gap_flag=True,
            exception_flag=True,
        )


def test_decision_register_rejects_na():
    with pytest.raises(ValueError):
        DecisionRegisterEntry(
            jira_issue_key="ABC-1",
            release_id="2.5",
            classification=Classification.NA,
            source=Source.RULE,
            confidence=1.0,
            owner="pm",
            context="x",
            rationale="x",
        )
