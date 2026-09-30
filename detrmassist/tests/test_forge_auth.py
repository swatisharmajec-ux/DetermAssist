"""
Exercises the real signature-verification path in app/auth/forge_auth.py
with an actual RSA keypair generated in-test — not mocked. The
signing_key_resolver injection point exists specifically so this can test
real cryptographic verification without needing Atlassian's live JWKS
endpoint or a registered Forge app.
"""
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import forge_auth

APP_ID = "test-forge-app-id"


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


@pytest.fixture(autouse=True)
def configured_app_id(monkeypatch):
    monkeypatch.setattr(forge_auth.settings, "forge_app_id", APP_ID)


def make_token(private_key, installation_id="site-abc-123", aud=APP_ID, exp_delta=3600, extra_claims=None):
    claims = {"aud": aud, "exp": int(time.time()) + exp_delta}
    if installation_id is not None:
        claims["installationId"] = installation_id
    if extra_claims:
        claims.update(extra_claims)
    return pyjwt.encode(claims, private_key, algorithm="RS256")


def test_valid_token_verifies_and_returns_claims(keypair):
    private_key, public_pem = keypair
    token = make_token(private_key)
    claims = forge_auth.verify_forge_invocation_token(
        f"Bearer {token}", signing_key_resolver=lambda t: public_pem
    )
    assert claims["installationId"] == "site-abc-123"


def test_missing_bearer_prefix_rejected(keypair):
    private_key, public_pem = keypair
    token = make_token(private_key)
    with pytest.raises(ValueError, match="malformed Authorization header"):
        forge_auth.verify_forge_invocation_token(token, signing_key_resolver=lambda t: public_pem)


def test_missing_header_rejected():
    with pytest.raises(ValueError, match="missing or malformed"):
        forge_auth.verify_forge_invocation_token(None)


def test_wrong_audience_rejected(keypair):
    private_key, public_pem = keypair
    token = make_token(private_key, aud="someone-elses-app-id")
    with pytest.raises(pyjwt.InvalidAudienceError):
        forge_auth.verify_forge_invocation_token(
            f"Bearer {token}", signing_key_resolver=lambda t: public_pem
        )


def test_expired_token_rejected(keypair):
    private_key, public_pem = keypair
    token = make_token(private_key, exp_delta=-60)  # expired one minute ago
    with pytest.raises(pyjwt.ExpiredSignatureError):
        forge_auth.verify_forge_invocation_token(
            f"Bearer {token}", signing_key_resolver=lambda t: public_pem
        )


def test_missing_installation_id_rejected(keypair):
    private_key, public_pem = keypair
    token = make_token(private_key, installation_id=None)
    with pytest.raises(ValueError, match="installationId"):
        forge_auth.verify_forge_invocation_token(
            f"Bearer {token}", signing_key_resolver=lambda t: public_pem
        )


def test_token_signed_by_wrong_key_rejected(keypair):
    """The actual attack this whole mechanism exists to stop: someone who
    doesn't hold Atlassian's private key cannot forge a valid token, even
    if they know the exact claim shape we expect."""
    _, real_public_pem = keypair
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged_token = make_token(attacker_key)  # signed with a DIFFERENT private key
    with pytest.raises(pyjwt.InvalidSignatureError):
        forge_auth.verify_forge_invocation_token(
            f"Bearer {forged_token}", signing_key_resolver=lambda t: real_public_pem
        )


def test_tampered_payload_rejected(keypair):
    private_key, public_pem = keypair
    token = make_token(private_key, installation_id="victim-tenant")
    header, payload, signature = token.split(".")
    # Flip the installationId claim without re-signing — this is exactly
    # what a forged cross-tenant request would look like.
    import base64
    import json
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
    decoded["installationId"] = "attacker-tenant"
    tampered_payload = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode().rstrip("=")
    tampered_token = f"{header}.{tampered_payload}.{signature}"
    with pytest.raises(pyjwt.InvalidSignatureError):
        forge_auth.verify_forge_invocation_token(
            f"Bearer {tampered_token}", signing_key_resolver=lambda t: public_pem
        )
