"""
Seed script — populates the DetrmAssist DB with realistic demo data so
every part of the system has something to show: a pending Gap, a confirmed
Gap, an Exception, captured Decisions (both rule-sourced and PM-override,
one with a rollback), and a Layer 4 self-healing example (a Gap pattern
already promoted into a rule) — spread across two releases so the release
filter has something to filter. Also seeds a handful of Layer 1 field
classifications independent of any disruption.

Run from the project root:
    python -m scripts.seed_demo_data
"""
from datetime import datetime, timedelta

from app.db import SessionLocal, engine
from app.models import (
    Base, Classification, DecisionRegisterEntry, DisruptionEvent,
    DisruptionTrigger, FieldClassification, RecordStatus,
    ResilienceTraceLogEntry, Resolution, Source, Tenant, TenantStatus,
)


def wipe_and_init():
    """Demo data only — safe to drop and recreate on every run."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed(db):
    now = datetime.utcnow()

    # Matches DEV_BYPASS_INSTALLATION_ID in the README's local-dev
    # instructions — without this exact match, the console (which sends
    # no Authorization header locally) would resolve to a different,
    # freshly-provisioned empty tenant instead of seeing this data.
    tenant = Tenant(installation_id="local-dev", status=TenantStatus.ACTIVE)
    db.add(tenant)
    db.flush()

    # ------------------------------------------------------------------
    # Layer 1 — field classifications, independent of any disruption.
    # This is the base signal everything else reads from.
    # ------------------------------------------------------------------
    db.add_all([
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-101", field_name="priority", raw_value="critical",
                             classification=Classification.ENFORCEMENT, source=Source.RULE, confidence=1.0),
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-101", field_name="resolution", raw_value="Fixed",
                             classification=Classification.DECISION, source=Source.RULE, confidence=1.0),
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-101", field_name="assignee", raw_value="jdoe",
                             classification=Classification.NA, source=Source.RULE, confidence=1.0),
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-102", field_name="comment:4821",
                             raw_value="We decided to descope this due to a blocked dependency on PROJ-099.",
                             classification=Classification.DECISION, source=Source.RULE, confidence=0.65),
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-104", field_name="description",
                             raw_value="Had lunch with the team, nice weather today.",
                             classification=Classification.NA, source=Source.RULE, confidence=0.5),
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-107", field_name="comment:5190",
                             raw_value="This is trending up again \u2014 third time this quarter we've seen this exact pattern.",
                             classification=Classification.TREND, source=Source.LLM, confidence=0.72),
        FieldClassification(tenant_id=tenant.id, jira_issue_key="PROJ-110", field_name="labels", raw_value="compliance",
                             classification=Classification.ENFORCEMENT, source=Source.RULE, confidence=1.0),
    ])

    # ------------------------------------------------------------------
    # Release 2.5 — one of each resolution state
    # ------------------------------------------------------------------

    # 1. Unexplained disruption, still waiting on a PM. Shows in the queue.
    ev1 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-101", release_id="2.5",
        trigger=DisruptionTrigger.FIX_VERSION_CHANGED,
        detected_at=now - timedelta(hours=3),
        resolution=Resolution.GAP,
    )
    db.add(ev1); db.flush()
    rtl1 = ResilienceTraceLogEntry(tenant_id=tenant.id, 
        disruption_event_id=ev1.id, jira_issue_key=ev1.jira_issue_key, release_id=ev1.release_id,
        gap_flag=True, exception_flag=False, status=RecordStatus.PROPOSED,
    )
    db.add(rtl1); db.flush()
    ev1.trace_log_id = rtl1.id

    # 2. Confirmed Gap — a PM already reviewed it and agreed it's real
    # governance debt. Stays flagged; nothing about "confirmed" means resolved.
    ev2 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-104", release_id="2.5",
        trigger=DisruptionTrigger.STATUS_REGRESSION,
        detected_at=now - timedelta(days=1, hours=2),
        resolution=Resolution.GAP, resolved_at=now - timedelta(hours=20),
    )
    db.add(ev2); db.flush()
    rtl2 = ResilienceTraceLogEntry(tenant_id=tenant.id, 
        disruption_event_id=ev2.id, jira_issue_key=ev2.jira_issue_key, release_id=ev2.release_id,
        gap_flag=True, exception_flag=False, status=RecordStatus.CONFIRMED,
        resolved_at=now - timedelta(hours=20),
    )
    db.add(rtl2); db.flush()
    ev2.trace_log_id = rtl2.id

    # 3. Exception — off-tool cause, captured via the Mail listener.
    ev3 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-107", release_id="2.5",
        trigger=DisruptionTrigger.BLOCKED_UNRESOLVED,
        detected_at=now - timedelta(days=2),
        resolution=Resolution.EXCEPTION, resolved_at=now - timedelta(days=1, hours=18),
    )
    db.add(ev3); db.flush()
    rtl3 = ResilienceTraceLogEntry(tenant_id=tenant.id, 
        disruption_event_id=ev3.id, jira_issue_key=ev3.jira_issue_key, release_id=ev3.release_id,
        gap_flag=False, exception_flag=True, status=RecordStatus.CONFIRMED,
        exception_context="VP redirected priority verbally in the Tuesday leadership sync \u2014 not captured in Jira until this report.",
        exception_reported_by="jane.pm@company.com",
        resolved_at=now - timedelta(days=1, hours=18),
    )
    db.add(rtl3); db.flush()
    ev3.trace_log_id = rtl3.id

    # 4. Captured decision — resolved automatically by the rule layer at
    # creation time, no PM involved.
    ev4 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-102", release_id="2.5",
        trigger=DisruptionTrigger.PRIORITY_DOWNGRADE,
        detected_at=now - timedelta(days=1, hours=6),
        resolution=Resolution.CAPTURED_DECISION, resolved_at=now - timedelta(days=1, hours=6),
    )
    db.add(ev4); db.flush()
    dr4 = DecisionRegisterEntry(tenant_id=tenant.id, 
        disruption_event_id=ev4.id, jira_issue_key=ev4.jira_issue_key, release_id=ev4.release_id,
        classification=Classification.DECISION, source=Source.RULE, confidence=0.8,
        owner="unassigned",
        context="We decided to descope this due to a blocked dependency on PROJ-099.",
        rationale="Auto-resolved from disruption trigger priority_downgrade.",
        status=RecordStatus.PROPOSED,
    )
    db.add(dr4); db.flush()
    ev4.decision_register_id = dr4.id

    # 5. Captured decision via PM override, including a rollback — shows
    # the rollback governance path (Section 5).
    ev5 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-110", release_id="2.5",
        trigger=DisruptionTrigger.EPIC_UNLINKED,
        detected_at=now - timedelta(days=4),
        resolution=Resolution.CAPTURED_DECISION, resolved_at=now - timedelta(days=3, hours=20),
    )
    db.add(ev5); db.flush()
    dr5 = DecisionRegisterEntry(tenant_id=tenant.id, 
        disruption_event_id=ev5.id, jira_issue_key=ev5.jira_issue_key, release_id=ev5.release_id,
        classification=Classification.ENFORCEMENT, source=Source.PM_OVERRIDE, confidence=1.0,
        owner="marcus.lee",
        context="Unlinked from the compliance epic while the policy review was in progress.",
        rationale="Compliance gate required re-review before re-linking; done manually by the PM.",
        status=RecordStatus.CONFIRMED,
        rollback_flag=True,
        rollback_reason="Re-linked to the epic three days later once compliance signed off \u2014 the original unlink was cautious, not incorrect.",
        reviewed_at=now - timedelta(days=1),
    )
    db.add(dr5); db.flush()
    ev5.decision_register_id = dr5.id

    # ------------------------------------------------------------------
    # Release 2.6 — a fresh pending Gap (exercises the release filter)
    # plus a Layer 4 example: a Gap pattern already mined and promoted
    # into a new rule-layer trigger.
    # ------------------------------------------------------------------

    ev6 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-201", release_id="2.6",
        trigger=DisruptionTrigger.FIX_VERSION_CHANGED,
        detected_at=now - timedelta(hours=1),
        resolution=Resolution.GAP,
    )
    db.add(ev6); db.flush()
    rtl6 = ResilienceTraceLogEntry(tenant_id=tenant.id, 
        disruption_event_id=ev6.id, jira_issue_key=ev6.jira_issue_key, release_id=ev6.release_id,
        gap_flag=True, exception_flag=False, status=RecordStatus.PROPOSED,
    )
    db.add(rtl6); db.flush()
    ev6.trace_log_id = rtl6.id

    ev7 = DisruptionEvent(tenant_id=tenant.id, 
        jira_issue_key="PROJ-150", release_id="2.6",
        trigger=DisruptionTrigger.PRIORITY_DOWNGRADE,
        detected_at=now - timedelta(days=10),
        resolution=Resolution.GAP, resolved_at=now - timedelta(days=9),
    )
    db.add(ev7); db.flush()
    rtl7 = ResilienceTraceLogEntry(tenant_id=tenant.id, 
        disruption_event_id=ev7.id, jira_issue_key=ev7.jira_issue_key, release_id=ev7.release_id,
        gap_flag=True, exception_flag=False, status=RecordStatus.CONFIRMED,
        disruption_reason="tech_debt_reprioritization",
        promoted_to_rule=True,
        digest_month="2026-07",
        resolved_at=now - timedelta(days=9),
    )
    db.add(rtl7); db.flush()
    ev7.trace_log_id = rtl7.id

    db.commit()


def summarize(db):
    print("Seeded:")
    print(f"  Field classifications: {db.query(FieldClassification).count()}")
    print(f"  Disruption events:     {db.query(DisruptionEvent).count()}")
    print(f"  Decision Register:     {db.query(DecisionRegisterEntry).count()}")
    print(f"  Resilience Trace Log:  {db.query(ResilienceTraceLogEntry).count()}")
    pending = db.query(ResilienceTraceLogEntry).filter_by(status=RecordStatus.PROPOSED, gap_flag=True).count()
    exceptions = db.query(ResilienceTraceLogEntry).filter_by(exception_flag=True).count()
    promoted = db.query(ResilienceTraceLogEntry).filter_by(promoted_to_rule=True).count()
    print(f"    ...pending review:   {pending}")
    print(f"    ...exceptions:       {exceptions}")
    print(f"    ...promoted to rule: {promoted}")


if __name__ == "__main__":
    wipe_and_init()
    db = SessionLocal()
    try:
        seed(db)
        summarize(db)
    finally:
        db.close()
