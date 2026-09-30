"""
Integration tests for the ingestion endpoints — these exercise the full
path from a raw payload to a written row, through the real FastAPI app and
a real (in-memory) DB, not just the pure parsing functions.
"""

JIRA_PAYLOAD_UNEXPLAINED = {
    "issue": {
        "key": "PROJ-301",
        "fields": {
            "fixVersions": [{"name": "3.0"}],
            "epic": {"key": "PROJ-300"},
        },
    },
    "changelog": {
        "items": [
            {"field": "fixVersions", "fromString": "2.9", "toString": "3.0"},
        ]
    },
}

JIRA_PAYLOAD_EXPLAINED = {
    "issue": {
        "key": "PROJ-302",
        "fields": {
            "fixVersions": [{"name": "3.0"}],
            "priority": "Minor",
            "comment": {"comments": [
                {"body": "We decided to downgrade this — it's not blocking launch."}
            ]},
        },
    },
    "changelog": {
        "items": [
            {"field": "priority", "fromString": "Critical", "toString": "Minor"},
        ]
    },
}

JIRA_PAYLOAD_NO_WATCHED_CHANGE = {
    "issue": {"key": "PROJ-303", "fields": {"fixVersions": [{"name": "3.0"}]}},
    "changelog": {"items": [{"field": "assignee", "fromString": "alice", "toString": "bob"}]},
}


def test_webhook_unexplained_change_creates_gap(client):
    r = client.post("/webhooks/jira", json=JIRA_PAYLOAD_UNEXPLAINED)
    assert r.status_code == 200
    assert r.json()["events_created"] == 1

    queue = client.get("/disruptions/?needs_review=true").json()
    assert len(queue) == 1
    assert queue[0]["jira_issue_key"] == "PROJ-301"
    # fix_version_changed disrupts the release being left, not the one
    # being entered.
    assert queue[0]["release_id"] == "2.9"


def test_webhook_explained_change_captures_decision(client):
    r = client.post("/webhooks/jira", json=JIRA_PAYLOAD_EXPLAINED)
    assert r.status_code == 200
    assert r.json()["events_created"] == 1

    decisions = client.get("/decisions/").json()
    assert len(decisions) == 1
    assert decisions[0]["jira_issue_key"] == "PROJ-302"
    assert decisions[0]["classification"] == "D"


def test_webhook_no_watched_field_creates_nothing(client):
    r = client.post("/webhooks/jira", json=JIRA_PAYLOAD_NO_WATCHED_CHANGE)
    assert r.status_code == 200
    assert r.json()["events_created"] == 0


def test_webhook_missing_issue_key_rejected(client):
    r = client.post("/webhooks/jira", json={"changelog": {"items": []}})
    assert r.status_code == 400


def test_mail_listener_reclassifies_matching_gap(client):
    client.post("/webhooks/jira", json=JIRA_PAYLOAD_UNEXPLAINED)
    r = client.post("/webhooks/mail", json={
        "issue_key": "PROJ-301", "release_id": "2.9",
        "from": "vp@company.com", "body": "Redirected verbally in the leadership sync.",
    })
    assert r.status_code == 200
    assert r.json()["resolution"] == "exception"

    trace_log = client.get("/trace-log/").json()
    entry = next(t for t in trace_log if t["jira_issue_key"] == "PROJ-301")
    assert entry["exception_flag"] is True
    assert entry["exception_reported_by"] == "vp@company.com"


def test_mail_listener_no_matching_gap_404s(client):
    r = client.post("/webhooks/mail", json={
        "issue_key": "PROJ-999", "release_id": "1.0", "from": "x@y.com", "body": "context",
    })
    assert r.status_code == 404
