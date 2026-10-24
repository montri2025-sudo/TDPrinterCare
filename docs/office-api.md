# TD ServicePro — Read-only Office API (for TDPrintSpace)

Status: **implemented locally for review. Not deployed, not verified against PostgreSQL, not connected to any live system.**

A small, authenticated, single-center, read-only JSON API that lets a future **server-side** TDPrintSpace
adapter poll a full snapshot of technicians, assigned repair jobs and their source status, so a 3D office can
be drawn. Code: `integration_api.py` (+ a 6-line hook in `app.py`, one method in `db.py`). Tests: `tests/`.

## 1. Contract at a glance

| | |
|---|---|
| `GET /api/v1/office/snapshot` | Full current snapshot for the one configured center |
| `GET /api/v1/office/capabilities` | Static description: statuses (+ Thai labels), limits, semantics |
| Auth | `Authorization: Bearer <token>` (server-to-server only) |
| Scope | Fixed by server configuration to **one** center. Never widened by the request |
| Format | JSON, UTF-8, `Cache-Control: no-store`, no CORS headers |
| Methods | `GET` only. Everything else: `405` |
| Query parameters | Only `center_id=<configured id>` (optional, must equal the configured center) |

Nothing else exists: no writes, no events/webhooks, no history, no stock, no customers, no Odoo.

## 2. Request / response

```
GET /api/v1/office/snapshot HTTP/1.1
Host: servicepro.example.com
Authorization: Bearer <TOKEN>
```

Response `200` (real output of the handler against a fictional 2-technician / 3-job fixture):

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-15T05:00:00Z",
  "revision": "rev-7f929af5aa34d83899c5c52c063f31e6",
  "complete": true,
  "scope": { "center_id": 1, "center_name": "Example Branch" },
  "limits": { "max_jobs": 500, "closed_job_window_days": 7 },
  "technicians": [
    { "user_id": 11, "display_name": "Alex Example", "role": "technician",
      "center_id": 1, "is_active": true, "availability": "unknown" },
    { "user_id": 12, "display_name": "Sam Example", "role": "technician_lead",
      "center_id": 1, "is_active": true, "availability": "unknown" }
  ],
  "jobs": [
    { "ticket_id": 201, "center_id": 1, "status": "In Repair", "assigned_tech_id": 11,
      "assignee_in_scope": true,
      "device": { "ref": "dev_16cc010ead36673c68761494", "model": "Example Printer A", "type": "FDM" },
      "closed_at": null },
    { "ticket_id": 202, "center_id": 1, "status": "New", "assigned_tech_id": null,
      "assignee_in_scope": null,
      "device": { "ref": "dev_ea0d6f37666ce6422c0a7de9", "model": "Example Printer B", "type": "Resin" },
      "closed_at": null },
    { "ticket_id": 203, "center_id": 1, "status": "Resolved/Closed", "assigned_tech_id": 12,
      "assignee_in_scope": true,
      "device": { "ref": "dev_16cc010ead36673c68761494", "model": "Example Printer A", "type": "FDM" },
      "closed_at": "2026-10-14 16:30:00" }
  ]
}
```

(The real response is compact JSON; pretty-printed here. Key order is not significant.)

### Field meanings

| Field | Meaning / caveat |
|---|---|
| `schema_version` | Contract version. Additive changes keep `1`; breaking changes bump it. |
| `generated_at` | UTC time the snapshot was built. **Not** part of `revision`. |
| `revision` | `rev-` + 32 hex of SHA-256 over the canonical JSON of `schema_version`, `scope`, `technicians`, `jobs`. Same exported business data ⇒ same revision. Changes when an exported field changes (assignment, status, display name, active flag, center name, device model/type, a job entering/leaving the set). Rotating `INTEGRATION_API_DEVICE_REF_KEY` also changes it. A closed job aging out of the window changes it without any database change. |
| `complete` | Always `true` on `200`. A snapshot is complete or an error (never a partial page). |
| `scope` | The configured center (id + name). |
| `limits` | Effective bounds (see §5). |
| `technicians[].user_id` | **Stable ServicePro `Users.user_id`.** Map people by this, never by name. |
| `technicians[].display_name` | `Users.name`; may change; may be Thai. |
| `technicians[].role` | `technician` or `technician_lead`. **Leads are included**: the app assigns tickets to leads exactly like technicians (`assigned_tech_id`) and its assignment/workload lists use both roles. Managers, admins, sales, customers are never exported. |
| `technicians[].center_id` | Always the configured center. |
| `technicians[].is_active` | Account active. Active technicians of the center are always listed (even with no jobs). Inactive ones are listed **only** while an exported job is still assigned to them. |
| `technicians[].availability` | Always `"unknown"`. ServicePro has no schedule/attendance data. A repair status is not presence, and not store coverage. |
| `jobs[].ticket_id` | Stable `Tickets.ticket_id`. |
| `jobs[].status` | Source value, unchanged: `New`, `Diagnosing`, `Waiting for Parts`, `In Repair`, `Testing`, `Resolved/Closed`. Thai labels are in `/capabilities`. No derived states are invented. |
| `jobs[].assigned_tech_id` | `Tickets.assigned_tech_id`; `null` = unassigned. **Assigned ≠ accepted** (no acceptance event exists in the schema). |
| `jobs[].assignee_in_scope` | `true` if that id appears in `technicians`; `false` if the ticket points at a user outside the exported set (other center, no center, non-technician role) — the id is reported honestly but that person is not exported; `null` when unassigned. |
| `jobs[].device.ref` | Opaque stable reference `dev_` + 24 hex = truncated HMAC-SHA-256 of the device serial keyed with `INTEGRATION_API_DEVICE_REF_KEY`. Same physical device ⇒ same ref. **Raw serials are never exported** (customer property). |
| `jobs[].device.model` / `.type` | Printer model text and `FDM`/`Resin`/`Wash & Cure`/`Other`/`null`. |
| `jobs[].closed_at` | For closed jobs only: `YYYY-MM-DD HH:MM:SS` exactly as stored (**server-local time, no timezone** — see §9). Otherwise `null`. |

**Deliberately omitted:** customer name/phone/email/address/tax id, issue category and descriptions, technician
notes, attachments, payments/invoices/prices, parts/stock, CSAT, usernames/e-mails/phones of staff, raw serials,
booking details.

### Job selection and ordering
* All jobs of the configured center whose status is not `Resolved/Closed` (**open jobs**), plus
* closed jobs with `closed_at` within the last `closed_job_window_days` (default 7; `0` = none). Closed jobs
  with no `closed_at` (legacy data) are excluded.
* Jobs ordered by `ticket_id` ascending; technicians by `user_id` ascending. No cross-center joins: every
  row is filtered by the configured center id.

## 3. Capabilities

`GET /api/v1/office/capabilities` → `schema_version`, `scope.center_id`, `endpoints`, `source_statuses`
(workflow order), `status_labels_th`, `technician_roles`, `limits`, and a `semantics` block stating: polling only,
availability unknown, `assigned_means_accepted: false`, `result_recorded_means_closed: false`, writes none.
Same authentication as the snapshot.

## 4. Errors

All errors are JSON: `{"error": {"code": "...", "message": "..."}}` (never SQL, credentials, stack traces).

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_request` | unsupported/duplicate/malformed query parameter (names and values are never echoed), query string > 256 chars |
| 401 | `authentication_required` / `invalid_credentials` | missing, malformed, unknown or revoked token (`WWW-Authenticate: Bearer`) |
| 403 | `scope_forbidden` | `center_id` differs from the configured center |
| 404 | `not_found` | unknown path under `/api/v1/` |
| 405 | `method_not_allowed` | anything but GET (`Allow: GET`; no CORS preflight is served) |
| 413 | `snapshot_too_large` | more jobs than `max_jobs` (body includes `limit`) — **explicit refusal, never truncation** |
| 429 | `rate_limited` | over the per-minute budget; honour `Retry-After` |
| 500 | `internal_error` | unexpected failure (only the exception *type* is logged) |
| 503 | `integration_not_configured` | API disabled or configuration invalid/missing (**fail closed**), configured center does not exist |
| 503 | `data_unavailable` | database connection failed |

## 5. Limits and rate limiting

| Setting | Default | Range | Notes |
|---|---|---|---|
| `INTEGRATION_API_MAX_JOBS` | 500 | 1–5000 | exceeded ⇒ `413`; raise it or shrink the window |
| `INTEGRATION_API_CLOSED_WINDOW_DAYS` | 7 | 0–31 | recent-closure window |
| technicians | 500 (fixed) | – | exceeded ⇒ `413` |
| `INTEGRATION_API_RATE_LIMIT_PER_MIN` | 30 | 1–6000 | requests with a **valid** token, per process, fixed 1-minute window |
| `INTEGRATION_API_AUTH_FAIL_LIMIT_PER_MIN` | 20 | 1–6000 | failed-auth requests; a valid token bypasses this counter, so an attacker cannot lock the connector out |

A setting that is present but invalid makes the API fail closed (`503`) rather than silently using a default.
The rate limiter is a small per-process counter that only bounds load from the connector; general abuse
protection belongs to the existing reverse proxy.

## 6. Read consistency

The snapshot is read on one connection inside a PostgreSQL **`REPEATABLE READ`, `READ ONLY`** transaction
(`db._Conn.begin_read_only_snapshot()`), so center, technicians and jobs come from one point in time and the
database itself rejects any write attempted in that transaction. Only the three `SELECT` statements in
`integration_api.SQL_*` are used (a test rejects write keywords). A `GET` never changes stock, tickets, history,
users or Odoo data, and never calls the repair-logging/approval/sync code paths.

## 7. Authentication, scope and operator procedures

Credentials live **only** in server environments: the ServicePro `.env` holds a SHA-256 digest; the TDPrintSpace
server holds the token. Never in a browser, URL, repository, chat, or log. The token is high-entropy random, so
a plain SHA-256 digest is appropriate; comparison is `hmac.compare_digest`. No `Users` row or admin account is
created; the identity is a fixed, read-only, single-center capability.

### First-time setup (human operator, on the ServicePro host)
1. Generate credentials (prints the token **once**):
   ```
   python3 integration_api.py generate-token     # -> token + its SHA-256
   python3 integration_api.py generate-ref-key   # -> device reference key
   ```
2. Put the token **only** in the TDPrintSpace server's secret store.
3. In the ServicePro `.env` (not committed) set:
   ```
   INTEGRATION_API_TOKEN_SHA256=<sha256 from step 1>
   INTEGRATION_API_CENTER_ID=<the single center_id TDPrintSpace may see>
   INTEGRATION_API_DEVICE_REF_KEY=<key from step 1>
   ```
   `docker-compose.yml` already forwards these variables (empty ⇒ API disabled). `integration_api.py` is added to
   the Dockerfile `COPY` list.
4. Recreate the app container so it reads the environment.
5. Confirm a request without a token gives `401`, with the token gives `200`, and with `?center_id=<other>`
   gives `403`.

Scope rules: exactly one numeric center id. `all`, `*`, lists, `0`, empty or non-existent ids ⇒ `503`.
Broader access (several centers / all centers) is **not implemented**; it would be a separately reviewed change.

### Rotation (zero downtime)
1. Generate a new token (step 1 above).
2. Set `INTEGRATION_API_TOKEN_SHA256=<old_sha>,<new_sha>` (two digests are accepted) and recreate the container.
3. Switch the TDPrintSpace server to the new token; confirm it works.
4. Remove the old digest, recreate the container. The old token now returns `401`.

### Revocation / emergency stop
Remove the digest (or empty `INTEGRATION_API_TOKEN_SHA256`) and recreate the container: all calls fail
(`401` for a removed token, `503` when nothing is configured). Treat any token that appeared in a log or chat as
compromised and rotate it. Rotating `INTEGRATION_API_DEVICE_REF_KEY` changes every `device.ref` (the adapter must
treat refs as new identifiers).

### Transport
TLS is terminated by the existing trusted reverse proxy; do not expose the app container directly
(the compose file already publishes no port). The proxy must forward `Authorization` and must **not** log it or
the query string. `app.py`'s access log redacts query strings of `/api/` requests. Do not enable CORS.

## 8. Verification

Automated (isolated SQLite file built from the real `schema.sql`, fictional fixtures, no network/PostgreSQL):

```
python3 -m unittest discover -s tests -v      # 34 tests
```

Covered: scoped valid credential and minimal fields; missing/invalid/rotated/revoked tokens; missing and malformed
scope fails closed; `center_id` cannot widen scope; unassigned jobs and technicians without jobs; inactive and
out-of-scope assignees; source statuses preserved; renamed staff keep ids; availability `unknown`; stable
revision, revision changes for assignment/status/name changes, `generated_at` ignored, unrelated edits ignored;
explicit `413` bound and window boundaries; deterministic order; sanitized 500/503 bodies and logs; `no-store`
and no CORS on every response; token never in logs; DB content byte-identical before/after; only `SELECT`;
end-to-end through `app.application()` including log redaction.

**Not verifiable locally — do this on a disposable PostgreSQL (staging copy with fictional data) before any
deployment:**
1. `begin_read_only_snapshot()` works on psycopg2 and a write inside it is rejected
   (`psycopg2.errors.ReadOnlySqlTransaction`).
2. `?` → `%s` translation of the three queries and `LIMIT ?` parameter binding.
3. The `closed_at` text comparison against real data (`YYYY-MM-DD HH:MM:SS` strings).
4. Measure snapshot latency/size with realistic data before choosing a poll interval.

## 9. Limitations (honest list)

* Polling of whole snapshots only. Intermediate transitions between polls are invisible; there is no event
  feed, cursor, webhook or exactly-once delivery. A history feed would need a separately designed durable
  cursor and deduplication contract (the existing `Ticket_Status_History` is a possible source, not used here).
* "Assigned" is not "accepted"; recording a repair result is not "closed"; status ≠ physical presence.
* No schedule/attendance data ⇒ `availability` is always `unknown`.
* `closed_at` is stored as naive server-local text; the timezone is whatever the app host uses.
* One center per credential. A job assigned to a technician of another center shows `assignee_in_scope:false`.
* Rate limiting is per process (the app runs as a single threaded process).
* Not verified on PostgreSQL or in production; no production compatibility is claimed.

## 10. Unresolved decisions for the owner

1. Which single center id is authorized for the first connector.
2. Confirm `technician_lead` is shown in the office (included by default).
3. Confirm opaque device refs are sufficient; exporting raw serials needs a documented authorized need.
4. Whether `closed_at` should be normalized to an explicit timezone (needs the host timezone decision).
5. Poll interval and whether a durable event/history feed is wanted (separate ticket).
6. Where the staging PostgreSQL verification (§8) will run.

## 11. Deployment steps for later human execution
(Not performed.) Review → run tests → staging PostgreSQL verification (§8) → merge → build image
(includes `integration_api.py`) → perform §7 setup → verify with the three requests → give the token to the
TDPrintSpace server → monitor `[integration_api]` log lines and request volume.
