"""
Settings. Confidence thresholds live here because they're a tuning knob,
not a code change — expect these to move once the pilot generates real
volume (see Spec Section 4 / Addendum Layer 4).
"""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./detrmassist.db")

    # Jira OAuth (3LO) — stub values until real credentials are wired.
    jira_client_id: str = os.getenv("JIRA_CLIENT_ID", "")
    jira_client_secret: str = os.getenv("JIRA_CLIENT_SECRET", "")
    jira_redirect_uri: str = os.getenv("JIRA_REDIRECT_URI", "http://localhost:8000/auth/jira/callback")

    # LLM fallback (Spec Section 4) — the rule layer always runs first;
    # this key only gates whether the ambiguous-residue fallback can run.
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Rule-layer confidence below this triggers the LLM fallback. Applies to
    # non-empty text only — a genuinely empty field is NA at confidence 1.0
    # and never needs the fallback.
    llm_fallback_threshold: float = 0.55

    # Mail listener (Spec Section 3) — stub until a real inbound provider
    # (SendGrid Inbound Parse / IMAP poll) is wired.
    mail_listener_inbound_address: str = os.getenv("MAIL_LISTENER_ADDRESS", "")

    # Forge Remote auth — both required once the Forge app is registered.
    # forge_app_id: assigned by `forge create`, becomes the JWT `aud` claim
    # every Forge Invocation Token must match.
    # forge_jwks_url: confirm the exact current URL from
    # developer.atlassian.com/platform/forge/remote/essentials/ at
    # implementation time — not hardcoded here, Atlassian's endpoint
    # naming has changed before and this isn't a value worth guessing at.
    forge_app_id: str = os.getenv("FORGE_APP_ID", "")
    forge_jwks_url: str = os.getenv("FORGE_JWKS_URL", "")

    # LOCAL DEV ONLY. When set, requests with no Authorization header at
    # all fall back to this installation_id instead of getting a 401 — so
    # the browser console and manual curl testing keep working without a
    # real Forge deployment. Any request that DOES send an Authorization
    # header is still verified for real, unconditionally — this never
    # weakens actual token verification, it only fills the "no token sent"
    # case. Must be empty (the default) in any real deployment; nothing in
    # this codebase enforces that outside of you not setting the env var.
    dev_bypass_installation_id: str = os.getenv("DEV_BYPASS_INSTALLATION_ID", "")


settings = Settings()
