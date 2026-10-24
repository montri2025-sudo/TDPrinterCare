# Brief: future TDPrintSpace adapter for the ServicePro Office API

Audience: whoever builds the TDPrintSpace **backend** connector later. Nothing here is implemented in
TDPrintSpace; this ticket only provides the ServicePro side (see `office-api.md` for the contract).

## Shape
A server-side poller inside the TDPrintSpace backend. The browser/frontend never sees the ServicePro URL or
token and never calls ServicePro. The adapter exposes its own normalized data to the 3D office.

## Polling
* One loop, one in-flight request, request timeout (e.g. 10 s). Interval is **configuration**, not a constant.
  Choose it from measured snapshot latency/size and ServicePro load (start conservative, e.g. 15–30 s; the
  server budget is 30 requests/min by default). Do not promise instantaneous delivery.
* Backoff on failure: exponential with jitter (e.g. 5 s → 5 min cap), reset on success.
* `429`: wait `Retry-After`. `401`/`403`/`503 integration_not_configured`: stop fast retrying, alert an operator
  (credential/scope problem). `413`: configuration problem on the ServicePro side, alert. `5xx`/timeouts:
  transient, back off.
* Use `revision`: if unchanged since the last successful poll, nothing needs re-mapping.

## Stale handling
* Keep the **last known good** snapshot and its `generated_at`/receipt time. On any failure, mark the data
  *stale* in the UI (e.g. dim + "last updated …") after a configurable threshold.
* **Never** interpret a failed or missing response as "job deleted", "technician left" or "printer finished",
  and never fabricate movements/animations from an error.

## Identity mapping
* Map people by ServicePro `technicians[].user_id` (stable). Keep a TDPrintSpace-side table
  `servicepro_user_id → avatar/employee`. The demo ids (`emp-alex`, …) are **not** ServicePro ids; names can
  change and must never be the join key. `display_name` is for labels only.
* A new `user_id` appears in `technicians` ⇒ unmapped person: show a neutral avatar and flag for an admin to map.
* Jobs by `ticket_id`; printers by `device.ref` (opaque; do not try to reverse it). Treat a changed ref
  (key rotation) as a new device.

## Initial load without replay
* The first successful snapshot **initializes** state silently: place avatars/printers directly in their
  current state, no walking/entry animations replaying history.
* On later polls, animate only genuine differences between two consecutive snapshots, and treat them as
  *"changed since last seen"*, not as exact events: polling can miss intermediate transitions (e.g. `New` →
  `Testing` between polls) and may show several steps at once. Do not claim exactly-once or ordered events.
* After a long outage or restart, re-initialize silently instead of replaying the diff.

## Source-state mapping (suggested, adapter-owned)
Keep ServicePro's `status` string as the source of truth and map it to presentation separately; unknown values
fall back to a neutral state (the list is in `/capabilities`).

| ServicePro `status` | Possible office presentation |
|---|---|
| `New` (`assigned_tech_id = null`) | job on an "unassigned" board; no avatar movement |
| `New` / `Diagnosing` (assigned) | avatar at the bench of the assignee ("assigned", **not** "accepted") |
| `In Repair` | avatar working on the printer |
| `Waiting for Parts` | printer parked/waiting marker |
| `Testing` | printer in a test area |
| `Resolved/Closed` | recently-closed shelf for `closed_job_window_days`, then disappears |

Facts the adapter must not infer: `availability` is `unknown` — do **not** show people as present/on duty or
infer store coverage from repair data; "assigned" is not "accepted"; a job disappearing from the snapshot means
only "outside the window/scope" (closed long ago, or reassigned elsewhere), not "deleted". A job with
`assignee_in_scope:false` should show as assigned to someone outside this office.

## Security
Token only in the adapter's server secret store (never browser, repo, URL, logs). HTTPS only. Do not log
the `Authorization` header or full responses containing staff names at debug level in shared logs.
