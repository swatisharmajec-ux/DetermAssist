"""
Forge Remote authentication — verifies the Forge Invocation Token Atlassian
attaches to every request when our registered Forge app calls out to this
backend as its `remotes` endpoint. Per Atlassian's own Forge Remote
essentials doc: validate the JWT against Atlassian's published JWKS, check
`aud` matches our app's Application ID, and use the `installationId` claim
as the tenant key — Atlassian is explicit that installationId is
guaranteed present and durable across an app's lifetime, unlike other
identifiers a site might expose.

get_current_tenant() is the seam every route depends on. It's the only
thing that needs to change if the auth mechanism ever changes (e.g. a
future standalone OAuth path) — routes and services only ever see a
resolved Tenant, never the verification mechanics.

Two settings (FORGE_APP_ID, FORGE_JWKS_URL) are placeholders until the
Forge app is actually registered — see app/config.py.
"""
from typing import Callable, Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Tenant, TenantStatus

_jwks_client: Optional[PyJWKClient] = None


def _fetch_signing_key(token: str) -> str:
    """Real path: fetch and cache Atlassian's JWKS, resolve the key by `kid`."""
    global _jwks_client
    if not settings.forge_jwks_url:
        raise ValueError("FORGE_JWKS_URL not configured — set it once the Forge app is registered")
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.forge_jwks_url)
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_forge_invocation_token(
    authorization_header: Optional[str],
    signing_key_resolver: Callable[[str], str] = _fetch_signing_key,
) -> dict:
    """
    Raises ValueError on any verification failure — bad header shape,
    signature mismatch, wrong audience, expired token, or a missing
    installationId claim. signing_key_resolver is injectable specifically
    so tests can supply a known test key instead of fetching Atlassian's
    real JWKS over the network — see tests/test_forge_auth.py, which
    exercises this with a real generated keypair rather than mocking the
    verification logic itself.
    """
    if not authorization_header or not authorization_header.lower().startswith("bearer "):
        raise ValueError("missing or malformed Authorization header")
    token = authorization_header.split(" ", 1)[1]

    if not settings.forge_app_id:
        raise ValueError("FORGE_APP_ID not configured — set it once the Forge app is registered")

    signing_key = signing_key_resolver(token)
    claims = pyjwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=settings.forge_app_id,
        options={"require": ["exp", "aud"]},
    )

    if "installationId" not in claims:
        raise ValueError("token missing installationId claim")

    return claims


def get_current_tenant(request: Request, db: Session = Depends(get_db)) -> Tenant:
    """
    The dependency every route uses. Verifies the caller, then resolves
    (or just-in-time provisions) the Tenant row for that installation.
    Never trust a tenant id from anywhere else — not a query param, not a
    request body field. This function, and only this function, is allowed
    to decide which tenant a request belongs to.
    """
    auth_header = request.headers.get("authorization")

    if not auth_header and settings.dev_bypass_installation_id:
        # LOCAL DEV ONLY — see the setting's own comment in app/config.py.
        # Only reached when no Authorization header was sent at all; a
        # present-but-invalid header still fails verification normally.
        installation_id = settings.dev_bypass_installation_id
    else:
        try:
            claims = verify_forge_invocation_token(auth_header)
        except ValueError as e:
            raise HTTPException(401, f"Forge token verification failed: {e}")
        installation_id = claims["installationId"]

    tenant = db.query(Tenant).filter(Tenant.installation_id == installation_id).first()
    if not tenant:
        tenant = Tenant(installation_id=installation_id, status=TenantStatus.ACTIVE)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    elif tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(403, "tenant is not active")

    return tenant
