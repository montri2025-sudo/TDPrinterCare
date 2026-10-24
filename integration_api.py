#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""integration_api.py — read-only server-to-server API for TDPrintSpace ("3D office" view).

Scope of this module (see docs/office-api.md for the full contract):
  GET /api/v1/office/snapshot       full current snapshot: technicians + jobs of ONE configured center
  GET /api/v1/office/capabilities   static description of the contract (statuses, limits, semantics)

Design rules (deliberate, please keep them when changing this file):
  * READ ONLY. Only SELECT statements (see the SQL_* constants; a unit test rejects write keywords).
    The snapshot is read inside one REPEATABLE READ + READ ONLY transaction on PostgreSQL, so the
    technicians/jobs/center rows always come from one coherent point in time.
  * NOT a browser/session API. No cookies, no CSRF, no HTML. Authentication is a static bearer token
    whose SHA-256 digest is configured in the environment. Nothing is stored in the database and no
    Users row is created. Missing/invalid configuration fails closed (503) - there is no default scope.
  * Scope is fixed by configuration (INTEGRATION_API_CENTER_ID, exactly one center). Request
    parameters can never widen it: ?center_id= is accepted only when it equals the configured center.
  * Minimal data. No customer identity/contact data, no notes/descriptions, no attachments, no payment
    data, no raw device serial numbers (opaque HMAC device reference instead), no usernames/e-mails.
  * Honest limits. Bounded response (explicit 413, never silent truncation), no events, no
    availability/presence data ("unknown"), "assigned" is not "accepted".
  * Errors are generic JSON. SQL text, credentials, tokens and stack traces never reach the client,
    and the token never reaches the logs (the module never logs headers; app.py redacts query strings
    of /api/ requests in the access log).

The module deliberately does not import app.py or db.py at import time so it can be unit-tested with
an isolated database; app.py passes db.get_conn in.
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs

SCHEMA_VERSION = 1
API_PREFIX = "/api/v1/"
SNAPSHOT_PATH = "/api/v1/office/snapshot"
CAPABILITIES_PATH = "/api/v1/office/capabilities"

# Same role semantics as the rest of the app (assignment dropdown, workload, commission): staff who can be
# assigned repair jobs. technician_lead is INCLUDED because leads receive and work tickets exactly like
# technicians (assigned_tech_id may point at a lead) and they sit physically in the same office.
# Managers/admins/sales/customers are never exported.
TECH_ROLES = ("technician", "technician_lead")

DEFAULT_MAX_JOBS = 500
HARD_MAX_JOBS = 5000
MAX_TECHNICIANS = 500
DEFAULT_CLOSED_WINDOW_DAYS = 7
MAX_CLOSED_WINDOW_DAYS = 31
DEFAULT_RATE_LIMIT_PER_MIN = 30        # requests with a VALID token
DEFAULT_AUTH_FAIL_LIMIT_PER_MIN = 20   # requests with a missing/invalid token
MAX_QUERY_STRING_LEN = 256
MAX_TOKEN_LEN = 256
CLOSED_STATUS = "Resolved/Closed"      # source value, preserved as-is everywhere else

# ----------------------------------------------------------------------------------------------- SQL
# Parameter placeholders are "?" (db._Conn translates them to %s). Never put a literal question mark
# or percent sign in these strings. SELECT only.
SQL_CENTER = "SELECT center_id, name FROM Service_Centers WHERE center_id = ?"
SQL_TECHNICIANS = (
    "SELECT user_id, name, role, center_id, is_active FROM Users "
    "WHERE role IN ('technician', 'technician_lead') AND center_id = ? "
    "ORDER BY user_id ASC LIMIT ?"
)
SQL_JOBS = (
    "SELECT t.ticket_id, t.center_id, t.status, t.assigned_tech_id, t.closed_at, "
    "d.device_sn, d.model AS device_model, d.type AS device_type "
    "FROM Tickets t LEFT JOIN Devices d ON d.device_sn = t.device_sn "
    "WHERE t.center_id = ? AND (t.status <> 'Resolved/Closed' "
    "OR (t.closed_at IS NOT NULL AND t.closed_at >= ?)) "
    "ORDER BY t.ticket_id ASC LIMIT ?"
)
ALL_SQL = (SQL_CENTER, SQL_TECHNICIANS, SQL_JOBS)


class ApiError(Exception):
    def __init__(self, status, code, message, headers=None, extra=None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or []
        self.extra = extra or {}


# ------------------------------------------------------------------------------------------ config
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Config:
    def __init__(self, token_hashes, center_id, ref_key, max_jobs, closed_window_days,
                 rate_limit, auth_fail_limit):
        self.token_hashes = token_hashes
        self.center_id = center_id
        self.ref_key = ref_key
        self.max_jobs = max_jobs
        self.closed_window_days = closed_window_days
        self.rate_limit = rate_limit
        self.auth_fail_limit = auth_fail_limit


def _not_configured():
    return ApiError(503, "integration_not_configured",
                    "The integration API is not configured on this server.")


def _int_env(env, name, default, lo, hi):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not (lo <= int(raw) <= hi):
        raise _not_configured()  # explicitly set but invalid -> fail closed, never silently default
    return int(raw)


def load_config(env=None):
    """Read configuration from the environment on every request (so a revoked/rotated token takes
    effect after the process environment changes, i.e. after a restart). Fail closed on anything odd."""
    env = os.environ if env is None else env
    hashes = [h.strip().lower() for h in (env.get("INTEGRATION_API_TOKEN_SHA256") or "").split(",") if h.strip()]
    if not hashes or len(hashes) > 2 or not all(_HEX64.match(h) for h in hashes):
        raise _not_configured()
    center_raw = (env.get("INTEGRATION_API_CENTER_ID") or "").strip()
    # Exactly one explicit numeric center. "all", "*", lists and empty values are rejected on purpose.
    if not center_raw.isdigit() or int(center_raw) < 1:
        raise _not_configured()
    ref_key = (env.get("INTEGRATION_API_DEVICE_REF_KEY") or "").strip()
    if len(ref_key) < 32:
        raise _not_configured()
    return Config(
        token_hashes=hashes,
        center_id=int(center_raw),
        ref_key=ref_key.encode("utf-8"),
        max_jobs=_int_env(env, "INTEGRATION_API_MAX_JOBS", DEFAULT_MAX_JOBS, 1, HARD_MAX_JOBS),
        closed_window_days=_int_env(env, "INTEGRATION_API_CLOSED_WINDOW_DAYS",
                                    DEFAULT_CLOSED_WINDOW_DAYS, 0, MAX_CLOSED_WINDOW_DAYS),
        rate_limit=_int_env(env, "INTEGRATION_API_RATE_LIMIT_PER_MIN", DEFAULT_RATE_LIMIT_PER_MIN, 1, 6000),
        auth_fail_limit=_int_env(env, "INTEGRATION_API_AUTH_FAIL_LIMIT_PER_MIN",
                                 DEFAULT_AUTH_FAIL_LIMIT_PER_MIN, 1, 6000),
    )


# ------------------------------------------------------------------------------------ rate limiting
class _FixedWindowCounter:
    """Tiny per-process fixed-window counter (1 minute). Deliberately simple: it only bounds load from
    one connector; it is not a general DoS defence (put the reverse proxy in front for that)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._window = None
        self._count = 0

    def hit(self, limit, now):
        """Count one request; return None if allowed, else seconds until the window resets."""
        window = int(now // 60)
        with self._lock:
            if window != self._window:
                self._window, self._count = window, 0
            self._count += 1
            if self._count > limit:
                return max(1, int(60 - (now % 60)))
            return None

    def reset(self):
        with self._lock:
            self._window, self._count = None, 0


_valid_counter = _FixedWindowCounter()
_fail_counter = _FixedWindowCounter()


def reset_rate_limits():
    _valid_counter.reset()
    _fail_counter.reset()


# ----------------------------------------------------------------------------------------- auth
def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(environ):
    header = environ.get("HTTP_AUTHORIZATION") or ""
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token or len(token) > MAX_TOKEN_LEN:
        return ""  # present but unusable -> treated as invalid
    return token


def _token_valid(token, cfg):
    digest = hash_token(token)
    ok = False
    for h in cfg.token_hashes:  # no early exit: constant work for 1 or 2 configured hashes
        ok |= hmac.compare_digest(digest, h)
    return ok


def _auth_headers():
    return [("WWW-Authenticate", 'Bearer realm="tdsp-integration"')]


# --------------------------------------------------------------------------------------- response
_BASE_HEADERS = [
    ("Cache-Control", "no-store"),
    ("Pragma", "no-cache"),
    ("X-Content-Type-Options", "nosniff"),
]
# No Access-Control-* header is ever emitted: the only client is a server-side adapter (no CORS).

_STATUS_TEXT = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                405: "Method Not Allowed", 413: "Payload Too Large", 429: "Too Many Requests",
                500: "Internal Server Error", 503: "Service Unavailable"}


def _respond(start_response, status, payload, extra_headers=()):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))]
    headers += _BASE_HEADERS + list(extra_headers)
    start_response(f"{status} {_STATUS_TEXT.get(status, 'Error')}", headers)
    return [body]


def _error_payload(err):
    payload = {"error": {"code": err.code, "message": err.message}}
    payload["error"].update(err.extra)
    return payload


# --------------------------------------------------------------------------------------- snapshot
def _device_ref(ref_key, serial):
    """Opaque, stable, non-reversible reference to a customer device. HMAC (keyed) rather than a plain
    hash so serial numbers cannot be brute-forced/confirmed by someone who only has the API output."""
    if not serial:
        return None
    return "dev_" + hmac.new(ref_key, serial.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _utc_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_revision(core):
    """Deterministic revision of the exported business fields. `core` must not contain generated_at."""
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "rev-" + hashlib.sha256(canonical).hexdigest()[:32]


def build_snapshot(conn, cfg, now_utc, local_now):
    # One coherent read: REPEATABLE READ + READ ONLY transaction (PostgreSQL). The sqlite test double
    # implements the same hook with PRAGMA query_only.
    begin = getattr(conn, "begin_read_only_snapshot", None)
    if begin is None:
        raise RuntimeError("connection cannot start a read-only snapshot")
    begin()

    center = conn.execute(SQL_CENTER, (cfg.center_id,)).fetchone()
    if center is None:
        raise _not_configured()  # configured scope does not exist -> fail closed

    cutoff = (local_now - datetime.timedelta(days=cfg.closed_window_days)).strftime("%Y-%m-%d %H:%M:%S")
    job_rows = conn.execute(SQL_JOBS, (cfg.center_id, cutoff, cfg.max_jobs + 1)).fetchall()
    if len(job_rows) > cfg.max_jobs:
        raise ApiError(413, "snapshot_too_large",
                       "More jobs match than the configured limit; the snapshot is refused instead of "
                       "being truncated. Raise INTEGRATION_API_MAX_JOBS or shorten "
                       "INTEGRATION_API_CLOSED_WINDOW_DAYS.",
                       extra={"limit": cfg.max_jobs})
    tech_rows = conn.execute(SQL_TECHNICIANS, (cfg.center_id, MAX_TECHNICIANS + 1)).fetchall()
    if len(tech_rows) > MAX_TECHNICIANS:
        raise ApiError(413, "snapshot_too_large", "Too many technician records for this center.",
                       extra={"limit": MAX_TECHNICIANS})

    assigned_ids = {r["assigned_tech_id"] for r in job_rows if r["assigned_tech_id"] is not None}
    # Active technicians always; inactive ones only when an exported job still points at them, so that
    # every in-scope assigned_tech_id resolves to a record.
    technicians = [
        {
            "user_id": r["user_id"],
            "display_name": r["name"],
            "role": r["role"],
            "center_id": r["center_id"],
            "is_active": bool(r["is_active"]),
            "availability": "unknown",   # no schedule/attendance data exists in ServicePro
        }
        for r in tech_rows
        if r["is_active"] or r["user_id"] in assigned_ids
    ]
    in_scope_ids = {t["user_id"] for t in technicians}

    jobs = []
    for r in job_rows:
        assigned = r["assigned_tech_id"]
        closed = r["status"] == CLOSED_STATUS
        jobs.append({
            "ticket_id": r["ticket_id"],
            "center_id": r["center_id"],
            "status": r["status"],                       # source value, unchanged
            "assigned_tech_id": assigned,                # null = unassigned. Assigned is NOT "accepted".
            "assignee_in_scope": (assigned in in_scope_ids) if assigned is not None else None,
            "device": {
                "ref": _device_ref(cfg.ref_key, r["device_sn"]),
                "model": r["device_model"],
                "type": r["device_type"],
            },
            "closed_at": r["closed_at"] if closed else None,  # server-local time text as stored
        })

    core = {
        "schema_version": SCHEMA_VERSION,
        "scope": {"center_id": center["center_id"], "center_name": center["name"]},
        "technicians": technicians,
        "jobs": jobs,
    }
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_iso(now_utc),
        "revision": compute_revision(core),
        "complete": True,   # always a whole snapshot or an error - never a partial page
        "scope": core["scope"],
        "limits": {"max_jobs": cfg.max_jobs, "closed_job_window_days": cfg.closed_window_days},
        "technicians": technicians,
        "jobs": jobs,
    }
    return snapshot


def build_capabilities(cfg, status_labels):
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {"center_id": cfg.center_id},
        "endpoints": [{"method": "GET", "path": SNAPSHOT_PATH}, {"method": "GET", "path": CAPABILITIES_PATH}],
        "source_statuses": list(status_labels.keys()),
        "status_labels_th": dict(status_labels),
        "technician_roles": list(TECH_ROLES),
        "limits": {"max_jobs": cfg.max_jobs, "closed_job_window_days": cfg.closed_window_days,
                   "max_technicians": MAX_TECHNICIANS, "rate_limit_per_minute": cfg.rate_limit},
        "semantics": {
            "delivery": "polling of full current snapshots only; no events, webhooks or history feed",
            "availability": "unknown (ServicePro holds no schedule or attendance data)",
            "assigned_means_accepted": False,
            "result_recorded_means_closed": False,
            "writes": "none; this API is read-only",
        },
    }


# ---------------------------------------------------------------------------------- request handling
def _check_params(environ, cfg):
    qs = environ.get("QUERY_STRING") or ""
    if len(qs) > MAX_QUERY_STRING_LEN:
        raise ApiError(400, "invalid_request", "Query string too long.")
    if not qs:
        return
    try:
        params = parse_qs(qs, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
    except ValueError:
        raise ApiError(400, "invalid_request", "Malformed query string.")
    # Only one optional parameter exists. Values/names are never echoed back (they could be secrets).
    if set(params) - {"center_id"}:
        raise ApiError(400, "invalid_request", "Unsupported query parameter.")
    values = params.get("center_id", [])
    if len(values) != 1 or not values[0].isdigit():
        raise ApiError(400, "invalid_request", "center_id must be a single integer.")
    if int(values[0]) != cfg.center_id:
        raise ApiError(403, "scope_forbidden", "This credential is not authorized for the requested scope.")


def handle(environ, start_response, *, get_conn, status_labels, config_env=None, clock=None):
    """WSGI-style entry point for every path under /api/v1/. `clock()` -> (utc_datetime, local_datetime,
    monotonic_seconds) is injectable for tests."""
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET")
    conn = None
    try:
        if path not in (SNAPSHOT_PATH, CAPABILITIES_PATH):
            raise ApiError(404, "not_found", "Unknown API path.")
        if method != "GET":
            raise ApiError(405, "method_not_allowed", "Only GET is supported.", headers=[("Allow", "GET")])

        cfg = load_config(config_env)
        if clock is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            local_now, mono = datetime.datetime.now(), time.time()
        else:
            now_utc, local_now, mono = clock()

        token = _bearer_token(environ)
        if token is None:
            retry = _fail_counter.hit(cfg.auth_fail_limit, mono)
            if retry:
                raise ApiError(429, "rate_limited", "Too many failed requests.",
                               headers=[("Retry-After", str(retry))])
            raise ApiError(401, "authentication_required", "A bearer token is required.",
                           headers=_auth_headers())
        if not token or not _token_valid(token, cfg):
            # A valid token bypasses the failure counter, so an attacker cannot lock the connector out.
            retry = _fail_counter.hit(cfg.auth_fail_limit, mono)
            if retry:
                raise ApiError(429, "rate_limited", "Too many failed requests.",
                               headers=[("Retry-After", str(retry))])
            raise ApiError(401, "invalid_credentials", "The bearer token is not valid.",
                           headers=_auth_headers())

        retry = _valid_counter.hit(cfg.rate_limit, mono)
        if retry:
            raise ApiError(429, "rate_limited", "Request rate limit exceeded; poll less often.",
                           headers=[("Retry-After", str(retry))])

        _check_params(environ, cfg)

        if path == CAPABILITIES_PATH:
            return _respond(start_response, 200, build_capabilities(cfg, status_labels))

        try:
            conn = get_conn()
        except Exception as exc:  # connection failure -> unavailable (details only in the server log)
            print(f"[integration_api] database unavailable: {type(exc).__name__}", file=sys.stdout)
            raise ApiError(503, "data_unavailable", "Data is temporarily unavailable.")
        snapshot = build_snapshot(conn, cfg, now_utc, local_now)
        return _respond(start_response, 200, snapshot)
    except ApiError as err:
        return _respond(start_response, err.status, _error_payload(err), err.headers)
    except Exception as exc:  # never leak SQL, credentials or stack traces
        print(f"[integration_api] internal error: {type(exc).__name__}", file=sys.stdout)
        return _respond(start_response, 500, {"error": {"code": "internal_error",
                                                        "message": "Internal error."}})
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------- operator CLI (no network)
def _cli(argv):
    usage = ("usage: python3 integration_api.py generate-token | generate-ref-key | hash-token\n"
             "  generate-token   print a NEW random bearer token and its SHA-256 digest\n"
             "  generate-ref-key print a NEW random device-reference key\n"
             "  hash-token       read a token from stdin and print its SHA-256 digest")
    if len(argv) != 2:
        print(usage)
        return 2
    if argv[1] == "generate-token":
        token = "tdsp_int_" + secrets.token_urlsafe(32)
        print("Bearer token (shown ONCE - give it only to the TDPrintSpace server secret store):")
        print(token)
        print("INTEGRATION_API_TOKEN_SHA256 value for the ServicePro environment:")
        print(hash_token(token))
        return 0
    if argv[1] == "generate-ref-key":
        print(secrets.token_urlsafe(48))
        return 0
    if argv[1] == "hash-token":
        print(hash_token(sys.stdin.readline().strip()))
        return 0
    print(usage)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
