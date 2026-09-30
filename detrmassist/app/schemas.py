"""
Pydantic request/response contracts — what the scoring function constructs
and the FastAPI layer serializes. Kept separate from models.py (storage
shape) so the API contract can evolve independently (Section 5).
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models import Classification, Source, DisruptionTrigger


class FieldClassificationCreate(BaseModel):
    jira_issue_key: str
    field_name: str
    raw_value: Optional[str] = None


class DisruptionEventCreate(BaseModel):
    jira_issue_key: str
    release_id: str
    epic_key: Optional[str] = None
    trigger: DisruptionTrigger
    field_delta: Optional[str] = None
    # Not stored on the event itself — whatever explanatory text the caller
    # already found (a comment, a linked issue's summary) for the Section 2
    # step 2 lookup. None means "no explanation was found."
    linked_explanation_text: Optional[str] = None


class DisruptionResolveRequest(BaseModel):
    """Section 2 step 5 — the three things a PM can do with a proposed Gap."""
    action: str  # "confirm_gap" | "supply_reason" | "reclassify_exception"
    reason: Optional[str] = None
    owner: Optional[str] = None
    classification: Optional[str] = None  # required for supply_reason

    @field_validator("action")
    @classmethod
    def valid_action(cls, v: str) -> str:
        allowed = {"confirm_gap", "supply_reason", "reclassify_exception"}
        if v not in allowed:
            raise ValueError(f"action must be one of {allowed}")
        return v


class DecisionRegisterCreate(BaseModel):
    disruption_event_id: Optional[str] = None
    jira_issue_key: str
    release_id: str
    classification: Classification
    source: Source
    confidence: float = Field(ge=0.0, le=1.0)
    owner: str
    context: str
    rationale: str
    outcome: Optional[str] = None
    linked_reason: Optional[str] = None

    @field_validator("classification")
    @classmethod
    def no_na_in_dr(cls, v: Classification) -> Classification:
        if v == Classification.NA:
            raise ValueError("Decision Register entries must resolve to D/E/T/R — NA has no place here")
        return v


class ResilienceTraceLogCreate(BaseModel):
    disruption_event_id: Optional[str] = None
    jira_issue_key: str
    release_id: str
    gap_flag: bool
    exception_flag: bool
    exception_context: Optional[str] = None
    exception_reported_by: Optional[str] = None
    disruption_reason: Optional[str] = None

    @field_validator("exception_flag")
    @classmethod
    def mutually_exclusive(cls, v: bool, info) -> bool:
        if v and info.data.get("gap_flag"):
            raise ValueError("gap_flag and exception_flag are mutually exclusive")
        return v
