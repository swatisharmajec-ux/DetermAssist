"""
DetrmAssist — Decision Register / Resilience Trace Log schema, plus the
Layer 1 field-classification log that everything else reads from.

Implements Polaris_Classification_Gap_Spec_v1.md (Sections 1, 2, 3, 5) and
the Layer 3 addendum. Ground rules this file enforces on purpose:

  - NA is a valid, earned classification — never a fallback for "unsure."
  - gap_flag and exception_flag are mutually exclusive at confirmation time.
  - A Decision Register entry can never carry NA — if there's nothing to
    decide, it doesn't belong in the register.
  - Every row belongs to exactly one Tenant, and tenant_id is never
    accepted from a client-supplied value — only from the verified Forge
    auth context (see app/auth/forge_auth.py). A query that forgets to
    filter by tenant is a cross-customer data leak, not a bug in the
    ordinary sense — every list/get in this codebase must filter on it.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey, String, Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class Classification(str, enum.Enum):
    DECISION = "D"
    ENFORCEMENT = "E"
    TREND = "T"
    REVIEW = "R"
    NA = "NA"


class Source(str, enum.Enum):
    RULE = "rule"
    LLM = "llm"
    PM_OVERRIDE = "pm_override"


class RecordStatus(str, enum.Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"


class DisruptionTrigger(str, enum.Enum):
    """Section 2 — release-level disruption triggers the scoring function
    watches for. Deliberately excludes anything sprint-scoped."""
    FIX_VERSION_CHANGED = "fix_version_changed"
    STATUS_REGRESSION = "status_regression"
    EPIC_UNLINKED = "epic_unlinked"
    BLOCKED_UNRESOLVED = "blocked_unresolved"
    PRIORITY_DOWNGRADE = "priority_downgrade"


class Resolution(str, enum.Enum):
    CAPTURED_DECISION = "captured_decision"  # -> DecisionRegisterEntry
    GAP = "gap"                              # -> ResilienceTraceLogEntry
    EXCEPTION = "exception"                  # -> ResilienceTraceLogEntry
    PENDING = "pending"


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    UNINSTALLED = "uninstalled"


# ---------------------------------------------------------------------------
# Tenant — one row per installed Jira site. Keyed on Forge's
# `installationId` claim specifically, per Atlassian's own Forge Remote
# guidance: installationId is guaranteed present and durable across an
# app's lifetime; other identifiers (site URL, clientKey-style values)
# are not guaranteed to stay available. Every other table's tenant_id
# points here.
# ---------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    installation_id = Column(String(128), nullable=False, unique=True, index=True)
    site_url = Column(String(255), nullable=True)  # populated opportunistically if a claim provides it
    status = Column(SAEnum(TenantStatus), default=TenantStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uninstalled_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Layer 1 — every classified field, structured or free-text. The base
# signal every other construct traces back to.
# ---------------------------------------------------------------------------

class FieldClassification(Base):
    __tablename__ = "field_classifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    jira_issue_key = Column(String(32), nullable=False, index=True)
    field_name = Column(String(64), nullable=False)   # e.g. "status", "description", "comment:12345"
    raw_value = Column(Text, nullable=True)

    classification = Column(SAEnum(Classification), nullable=False)
    source = Column(SAEnum(Source), nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(SAEnum(RecordStatus), default=RecordStatus.PROPOSED, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# DisruptionEvent — the raw signal, written the moment a trigger fires,
# before the engine knows the resolution. Every DR/RTL row that originates
# from a disruption traces back to one of these.
# ---------------------------------------------------------------------------

class DisruptionEvent(Base):
    __tablename__ = "disruption_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    jira_issue_key = Column(String(32), nullable=False, index=True)
    release_id = Column(String(64), nullable=False, index=True)  # fix version
    epic_key = Column(String(32), nullable=True, index=True)

    trigger = Column(SAEnum(DisruptionTrigger), nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    field_delta = Column(Text, nullable=True)  # JSON-serialized before/after snapshot

    resolution = Column(SAEnum(Resolution), default=Resolution.PENDING, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    decision_register_id = Column(String(36), ForeignKey("decision_register.id"), nullable=True)
    trace_log_id = Column(String(36), ForeignKey("resilience_trace_log.id"), nullable=True)

    decision_register_entry = relationship(
        "DecisionRegisterEntry", back_populates="disruption_event", uselist=False,
        foreign_keys="DecisionRegisterEntry.disruption_event_id",
    )
    trace_log_entry = relationship(
        "ResilienceTraceLogEntry", back_populates="disruption_event", uselist=False,
        foreign_keys="ResilienceTraceLogEntry.disruption_event_id",
    )


# ---------------------------------------------------------------------------
# Decision Register — Phase 2, owned by DRC.
# ---------------------------------------------------------------------------

class DecisionRegisterEntry(Base):
    __tablename__ = "decision_register"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    disruption_event_id = Column(String(36), ForeignKey("disruption_events.id"), nullable=True)
    jira_issue_key = Column(String(32), nullable=False, index=True)
    release_id = Column(String(64), nullable=False, index=True)

    classification = Column(SAEnum(Classification), nullable=False)
    source = Column(SAEnum(Source), nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(SAEnum(RecordStatus), default=RecordStatus.PROPOSED, nullable=False)

    owner = Column(String(128), nullable=False)
    context = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    outcome = Column(Text, nullable=True)
    linked_reason = Column(String(64), nullable=True)

    rollback_flag = Column(Boolean, default=False, nullable=False)
    rollback_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)  # monthly DR review, Section 5

    disruption_event = relationship(
        "DisruptionEvent", back_populates="decision_register_entry",
        foreign_keys=[disruption_event_id],
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.classification == Classification.NA:
            raise ValueError(
                "Decision Register entries must resolve to D/E/T/R — NA has no place here"
            )


# ---------------------------------------------------------------------------
# Resilience Trace Log — Phase 3, owned by WSO.
# ---------------------------------------------------------------------------

class ResilienceTraceLogEntry(Base):
    __tablename__ = "resilience_trace_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    disruption_event_id = Column(String(36), ForeignKey("disruption_events.id"), nullable=True)
    jira_issue_key = Column(String(32), nullable=False, index=True)
    release_id = Column(String(64), nullable=False, index=True)

    gap_flag = Column(Boolean, nullable=False)
    exception_flag = Column(Boolean, nullable=False)
    status = Column(SAEnum(RecordStatus), default=RecordStatus.PROPOSED, nullable=False)

    # Populated only for Exceptions — intake via the Mail listener (Section 3)
    exception_context = Column(Text, nullable=True)
    exception_reported_by = Column(String(128), nullable=True)

    # Open item, Section 2: free text until real pattern volume justifies an
    # enum. `promoted_to_rule` is the Layer 4 self-healing marker — set when
    # ASD promotes a mined pattern into a new rule-layer trigger.
    disruption_reason = Column(String(64), nullable=True)
    promoted_to_rule = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    digest_month = Column(String(7), nullable=True, index=True)  # "YYYY-MM"

    disruption_event = relationship(
        "DisruptionEvent", back_populates="trace_log_entry",
        foreign_keys=[disruption_event_id],
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.gap_flag and self.exception_flag:
            raise ValueError(
                "gap_flag and exception_flag are mutually exclusive at confirmation (Section 5)"
            )
