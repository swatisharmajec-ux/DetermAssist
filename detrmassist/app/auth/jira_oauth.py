"""
Jira OAuth 2.0 (3LO). The authorize/callback flow is real; jira_client_id
and jira_client_secret are stubbed until real Atlassian app credentials are
issued (Marketplace app registration — next build priority alongside the
webhook subscription in app/ingestion/jira_webhook.py).
"""
import httpx
from fastapi import APIRouter, Request

from app.config import settings

router = APIRouter(prefix="/auth/jira", tags=["auth"])

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
SCOPES = "read:jira-work read:jira-user offline_access"


@router.get("/login")
def login():
    params = (
        f"audience=api.atlassian.com&client_id={settings.jira_client_id}"
        f"&scope={SCOPES}&redirect_uri={settings.jira_redirect_uri}"
        f"&response_type=code&prompt=consent"
    )
    return {"authorize_url": f"{AUTHORIZE_URL}?{params}"}


@router.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, json={
            "grant_type": "authorization_code",
            "client_id": settings.jira_client_id,
            "client_secret": settings.jira_client_secret,
            "code": code,
            "redirect_uri": settings.jira_redirect_uri,
        })
    return resp.json()
