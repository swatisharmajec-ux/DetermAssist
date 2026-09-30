"""
The test that actually matters for today's work: does the tenant boundary
hold under real API calls, not just exist in the schema. Two tenants,
same shared DB, real routes — tenant B must never see or touch tenant A's
data.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth.forge_auth import get_current_tenant
from app.db import get_db
from app.main import app
from app.models import Tenant, TenantStatus


@pytest.fixture()
def two_tenants(db_session):
    a = Tenant(installation_id="tenant-a", status=TenantStatus.ACTIVE)
    b = Tenant(installation_id="tenant-b", status=TenantStatus.ACTIVE)
    db_session.add_all([a, b])
    db_session.commit()
    db_session.refresh(a)
    db_session.refresh(b)
    return a, b


def _client_as(db_session, tenant):
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return TestClient(app)


def test_tenant_cannot_see_another_tenants_disruptions(db_session, two_tenants):
    tenant_a, tenant_b = two_tenants

    with _client_as(db_session, tenant_a) as client_a:
        r = client_a.post("/disruptions/", json={
            "jira_issue_key": "SECRET-1", "release_id": "1.0", "trigger": "fix_version_changed",
        })
        assert r.status_code == 200

    with _client_as(db_session, tenant_b) as client_b:
        # tenant B's own list must be empty, even though tenant A just wrote data
        assert client_b.get("/disruptions/").json() == []
        assert client_b.get("/decisions/").json() == []
        assert client_b.get("/trace-log/").json() == []

    app.dependency_overrides.clear()


def test_tenant_cannot_resolve_another_tenants_disruption_by_guessing_id(db_session, two_tenants):
    tenant_a, tenant_b = two_tenants

    with _client_as(db_session, tenant_a) as client_a:
        r = client_a.post("/disruptions/", json={
            "jira_issue_key": "SECRET-2", "release_id": "1.0", "trigger": "fix_version_changed",
        })
        event_id = r.json()["disruption_event_id"]

    with _client_as(db_session, tenant_b) as client_b:
        # tenant B has the real id (simulating a guessed/leaked id) but
        # must still be refused — this is the check that matters, not the
        # list endpoint filtering alone.
        r = client_b.patch(f"/disruptions/{event_id}/resolve", json={"action": "confirm_gap"})
        assert r.status_code == 404

    with _client_as(db_session, tenant_a) as client_a:
        # and tenant A's own data is untouched by tenant B's attempt
        queue = client_a.get("/disruptions/?needs_review=true").json()
        assert len(queue) == 1
        assert queue[0]["jira_issue_key"] == "SECRET-2"

    app.dependency_overrides.clear()


def test_each_tenant_gets_its_own_row_on_first_verified_call(db_session):
    """get_current_tenant just-in-time provisions — but only ever from a
    verified installationId, never from anything client-supplied."""
    from app.models import Tenant as TenantModel

    app.dependency_overrides[get_db] = lambda: (yield db_session)

    def fake_verify(auth_header, signing_key_resolver=None):
        return {"installationId": "brand-new-site"}

    import app.auth.forge_auth as forge_auth_module
    original = forge_auth_module.verify_forge_invocation_token
    forge_auth_module.verify_forge_invocation_token = fake_verify
    app.dependency_overrides.pop(get_current_tenant, None)

    try:
        with TestClient(app) as client:
            r = client.get("/decisions/", headers={"Authorization": "Bearer anything"})
            assert r.status_code == 200

        provisioned = db_session.query(TenantModel).filter_by(installation_id="brand-new-site").first()
        assert provisioned is not None
        assert provisioned.status == TenantStatus.ACTIVE
    finally:
        forge_auth_module.verify_forge_invocation_token = original
        app.dependency_overrides.clear()
