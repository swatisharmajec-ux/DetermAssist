import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.forge_auth import get_current_tenant
from app.db import get_db
from app.main import app
from app.models import Base, Tenant, TenantStatus


@pytest.fixture()
def db_session():
    # StaticPool is required here: sqlite's :memory: database is
    # per-connection, so without pinning the engine to a single connection
    # each query would silently get a fresh, empty database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def test_tenant(db_session):
    """A real, persisted Tenant row — most tests care about business logic,
    not Forge token verification, so this bypasses that (see
    tests/test_forge_auth.py for the dedicated test of the real
    verification path with a real signed token)."""
    tenant = Tenant(installation_id="test-installation-001", status=TenantStatus.ACTIVE)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


@pytest.fixture()
def client(db_session, test_tenant):
    def override_get_db():
        yield db_session

    def override_get_current_tenant():
        return test_tenant

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_tenant] = override_get_current_tenant
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
