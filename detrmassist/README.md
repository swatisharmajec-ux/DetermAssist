# DetrmAssist

The Jira-first classification engine behind DETRMAINA's plugin product line.
Implements `Polaris_Classification_Gap_Spec_v1.md` — every field, comment,
and release-level disruption resolves to D/E/T/R/NA, an explained Decision,
a proposed Gap, or a captured Exception.

**Platform note:** built to ship as a Forge app using the [Forge Remote](https://developer.atlassian.com/platform/forge/remote/essentials/)
pattern — this FastAPI service is the external backend Forge calls into,
not a Connect app. Connect closed to new Marketplace submissions on
September 16, 2025, so it was never a live option; Forge Remote lets this
codebase stay a normal, self-hosted service instead of a full rewrite onto
Atlassian's serverless runtime.

## Ground rules this codebase enforces in code, not just in the doc

- **NA is earned, never defaulted away from.** Ambiguous or signal-free
  text classifies NA. It never silently becomes D. (`app/scoring/classifier.py`,
  `tests/test_classifier.py`)
- **Gap and Exception are mutually exclusive at confirmation.** Enforced at
  the ORM level. (`app/models.py`, `tests/test_models.py`)
- **A Decision Register entry can never carry NA.** If there's nothing to
  decide, it doesn't belong in the register. (`app/models.py`)
- **Sprint membership is never inspected for disruption detection.**
  Release (`fix_version`) is the only tracking unit — sprints are too
  transient. (`app/scoring/disruption_detector.py`)
- **Every row belongs to exactly one tenant, and tenant_id never comes
  from the caller.** It's resolved once, server-side, from a verified
  Forge token, and every query filters by it. (`app/auth/forge_auth.py`,
  `app/models.py`, `tests/test_tenant_isolation.py`)

## Structure

```
app/
  config.py            settings + confidence thresholds + Forge/dev-bypass config
  models.py            Tenant, FieldClassification, DisruptionEvent,
                        DecisionRegisterEntry, ResilienceTraceLogEntry
  db.py                 SQLite by default; swap DATABASE_URL for Postgres later
  schemas.py            Pydantic request/response contracts
  auth/
    forge_auth.py         Forge Invocation Token verification + get_current_tenant(),
                           the one seam every route depends on for tenant identity
    jira_oauth.py          NOT on the active path — see note below
  scoring/
    classifier.py          Layer 1 — hybrid rule + LLM-fallback classifier
    disruption_detector.py Layer 2/3 — trigger detection + gap resolution
    resolution_service.py  create/resolve logic shared by the API and ingestion —
                            every read and write here requires tenant_id
  ingestion/
    jira_webhook.py       changelog -> FieldDelta parsing, writes through the
                           resolution service, tenant-scoped
    mail_listener.py      Exception intake channel (Section 3), tenant-scoped
  api/
    routes_disruptions.py  GET/POST /disruptions, PATCH /disruptions/{id}/resolve
    routes_decisions.py    GET /decisions
    routes_trace_log.py    GET /trace-log, PATCH /trace-log/{id}/promote
    routes_webhooks.py     POST /webhooks/jira, POST /webhooks/mail
tests/                    pytest — see "ground rules" above; test_forge_auth.py
                           and test_tenant_isolation.py are the ones that matter
                           most for the security posture specifically
```

`app/auth/jira_oauth.py` is old Connect-era scaffolding and isn't wired
into `main.py`'s active routes. Left in place only because a standalone
OAuth path may still matter down the line — don't confuse it with the
live auth mechanism, which is exclusively `forge_auth.py` for every route
that's actually wired today.

## Running locally

```
pip install -r requirements.txt --break-system-packages
DEV_BYPASS_INSTALLATION_ID=local-dev python -m scripts.seed_demo_data
DEV_BYPASS_INSTALLATION_ID=local-dev uvicorn app.main:app --reload
```

Then open **http://localhost:8000/** in a browser. `DEV_BYPASS_INSTALLATION_ID`
is a **local-dev-only** escape hatch (see the comment on it in
`app/config.py`): requests with no `Authorization` header at all resolve
to that installation id instead of getting a 401, so the console and
manual `curl` testing work without a real Forge deployment. A request
that *does* send an `Authorization` header is still verified for real,
unconditionally — this never weakens actual verification, it only fills
the "no token sent" case. Leave it unset for anything other than your own
machine. Run `pytest` separately for the test suite.

The seed script wipes and recreates the DB with one example of every
state the system can hold: a Gap waiting on review, a Gap a PM already
confirmed as real governance debt, an Exception captured off-tool, two
captured Decisions (one rule-resolved, one PM-override with a rollback),
and one Gap pattern already promoted into a rule — spread across two
releases so the release filter has something to filter. Safe to re-run
any time; it always starts from a clean slate, and it seeds its own
`local-dev` tenant matching the bypass value above.

## Frontend

`frontend/index.html` is the PM review console. Right now it's a plain
static file that calls the API with `fetch()` and no Authorization header
— which only works locally, via the dev bypass above. **It still needs to
be ported to a Forge Custom UI module** (swapping `fetch()` for Forge's
`invokeRemote`/`requestRemote` bridge) before this can run for real — see
priorities below. The HTML/CSS and all the review-queue logic carry over
unchanged; only the networking layer changes.

It implements the loop the founder specified directly: the engine proposes
a Gap, and the PM's three options — confirm it, supply the missing reason
(closes it into the Decision Register), or mark it an Exception — are the
only three actions the review queue offers. Styled on the established
DETRMAINA palette and the D/E/T/R badge pattern from the AINA site, for
visual consistency across the product suite.

## Ingestion

`POST /webhooks/jira` and `POST /webhooks/mail` are real, tested,
tenant-scoped endpoints that write straight into the Decision Register /
Resilience Trace Log via `app/scoring/resolution_service.py` — the same
path the API and the console use. Both expect a Forge Invocation Token
like every other route; in the shipped architecture, a small Forge
function (reacting to Jira's own event system) calls these, rather than
Atlassian posting to them directly the old Connect way.

A real bug worth knowing about: `app/scoring/disruption_detector.py`
originally compared field values case-sensitively against lowercase
fixtures ("critical", "to_do"), which happened to pass every unit test
written against synthetic lowercase data — but real Jira sends "Critical"
and "To Do". The webhook integration tests (`tests/test_webhooks.py`),
written against realistic payload shapes, caught this immediately. Fixed
with a normalization step; regression tests added. Worth remembering as a
pattern: synthetic test fixtures can pass while quietly not testing what
production data actually looks like.

## Security posture — what's real, what's still a placeholder

Enforced today: every route requires a verified tenant (`app/auth/forge_auth.py`),
every query and write is scoped to it, `tenant_id` is never accepted from
a client-supplied value, and `tests/test_tenant_isolation.py` proves one
tenant can't read or act on another tenant's data even with a guessed ID.
`tests/test_forge_auth.py` exercises the real cryptographic verification
path — valid tokens, forged signatures, tampered payloads, wrong audience,
expired tokens — with an actual generated keypair, not mocks.

Still placeholders, blocking a real deployment:
- `FORGE_APP_ID` / `FORGE_JWKS_URL` — real values only exist once the
  Forge app is registered (`forge create`). Confirm the exact current JWKS
  URL from Atlassian's docs at that point rather than trusting anything
  hardcoded here.
- SQLite — fine for one tenant's worth of local dev, wrong for real
  concurrent multi-tenant load. Swap `DATABASE_URL` for Postgres before
  any real pilot.
- No rate limiting, no background job queue for webhook processing, no
  structured audit logging of who called the API itself.

## Next build priorities (in order)

1. Register the Forge app (`forge create`), get the real `FORGE_APP_ID`
   and confirm the current JWKS URL
2. Build the actual Forge shell — `manifest.yml`, a `remotes` entry
   pointing at this backend, and the Custom UI module wrapping
   `frontend/index.html`
3. Port the frontend's `fetch()` calls to Forge's `invokeRemote`/`requestRemote`
4. Wire a Forge function (Jira event trigger) to call `POST /webhooks/jira`;
   same for the Mail listener provider and `POST /webhooks/mail`
5. Postgres migration before any real multi-tenant pilot
6. Sprint dashboard API — release-level rollups across multiple releases
7. Disruption reason taxonomy, once the pilot generates real Gap volume
   (currently free text on `ResilienceTraceLogEntry.disruption_reason` —
   deliberately not an enum yet, see spec Section 2)
