# -*- coding: utf-8 -*-
"""Tests for integration_api.py (read-only office snapshot API).

Run from the repository root:   python3 -m unittest discover -s tests -v

Isolation: every test builds a throw-away SQLite file in a temp dir from the REAL schema.sql and fills it
with FICTIONAL fixtures. No PostgreSQL, no network, no production configuration, no seed script and no
real credential is involved. The SQLite connection double implements the same begin_read_only_snapshot()
hook as db._Conn (PRAGMA query_only instead of a PostgreSQL READ ONLY transaction), so a write attempt
inside the snapshot would fail here too.

What these tests can NOT prove: PostgreSQL-specific behaviour (REPEATABLE READ/READ ONLY transaction
semantics, psycopg2 placeholder translation). Run the checklist in docs/office-api.md against a
disposable PostgreSQL before any deployment.
"""
import datetime
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import integration_api as api  # noqa: E402

STATUS_LABELS = {"New": "รอซ่อม", "Diagnosing": "กำลังตรวจสอบ", "Waiting for Parts": "รออะไหล่",
                 "In Repair": "กำลังซ่อม", "Testing": "ทดสอบ", "Resolved/Closed": "เรียบร้อยแล้ว"}

# ---- fictional secrets, only used inside tests ----
TOKEN = "tdsp_int_FICTIONAL_TEST_TOKEN_aaaaaaaaaaaaaaaaaaaaaa"
OLD_TOKEN = "tdsp_int_FICTIONAL_OLD_TOKEN_bbbbbbbbbbbbbbbbbbbbbbbb"
REF_KEY = "fictional-device-ref-key-0123456789abcdef0123456789"
SENTINELS = ["SENTINEL_CUSTOMER", "SENTINEL_PHONE", "SENTINEL_NOTES", "SENTINEL_LOGIN", "SENTINEL_MAIL",
             "SENTINEL_TAXID", "SENTINEL_ISSUE", "SENTINEL_ADDR", "FAKE-SN-"]

NOW_LOCAL = datetime.datetime(2026, 10, 15, 12, 0, 0)
NOW_UTC = datetime.datetime(2026, 10, 15, 5, 0, 0)


def _env(**overrides):
    env = {
        "INTEGRATION_API_TOKEN_SHA256": api.hash_token(TOKEN),
        "INTEGRATION_API_CENTER_ID": "1",
        "INTEGRATION_API_DEVICE_REF_KEY": REF_KEY,
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


class SqliteConn:
    """Test double with the same surface the module uses from db._Conn."""

    def __init__(self, path, fail_on=None):
        self._c = sqlite3.connect(path)
        self._c.row_factory = sqlite3.Row
        self.began = False
        self.closed = False
        self.statements = []
        self.fail_on = fail_on

    def begin_read_only_snapshot(self):
        self.began = True
        self._c.execute("PRAGMA query_only = ON")

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom: password=SECRETPW host=db.internal SELECT secret FROM x")
        return self._c.execute(sql, params)

    def close(self):
        self.closed = True
        self._c.close()


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _dump(path):
    c = sqlite3.connect(path)
    out = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        out[t] = c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
    c.close()
    return out


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        api.reset_rate_limits()
        self.tmp = tempfile.mkdtemp(prefix="tdsp_api_test_")
        self.path = os.path.join(self.tmp, "fixture.db")
        c = sqlite3.connect(self.path)
        with open(os.path.join(ROOT, "schema.sql"), encoding="utf-8") as f:
            for stmt in f.read().split(";"):
                if stmt.strip():
                    c.execute(stmt)
        self._fixtures(c)
        c.commit()
        c.close()
        self.conns = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- fixtures (all fictional)
    def _fixtures(self, c):
        c.executemany("INSERT INTO Service_Centers (center_id, name, address, phone, is_headquarters) VALUES (?,?,?,?,0)",
                      [(1, "Test Branch A", "SENTINEL_ADDR 1", "SENTINEL_PHONE"), (2, "Test Branch B", "x", "x")])
        c.execute("INSERT INTO Customers (customer_id, name, phone, email, address, tax_id) VALUES "
                  "(1,'SENTINEL_CUSTOMER','SENTINEL_PHONE','SENTINEL_MAIL','SENTINEL_ADDR','SENTINEL_TAXID')")
        users = [  # id, username, role, name, center, active
            (11, "SENTINEL_LOGIN_a1", "technician", "Alex Tester", 1, 1),
            (12, "SENTINEL_LOGIN_a2", "technician_lead", "Lead Tester", 1, 1),
            (13, "SENTINEL_LOGIN_a3", "technician", "Inactive With Job", 1, 0),
            (14, "SENTINEL_LOGIN_a4", "technician", "Inactive No Job", 1, 0),
            (15, "SENTINEL_LOGIN_a5", "technician", "Idle Tester", 1, 1),     # active, no jobs
            (20, "SENTINEL_LOGIN_c1", "customer", "Customer User", 1, 1),
            (21, "SENTINEL_LOGIN_m1", "manager", "Manager User", 1, 1),
            (31, "SENTINEL_LOGIN_b1", "technician", "Other Branch Tech", 2, 1),
            (41, "SENTINEL_LOGIN_n1", "technician", "No Center Tech", None, 1),
        ]
        for uid, uname, role, name, center, active in users:
            c.execute("INSERT INTO Users (user_id, username, password, role, name, center_id, is_active, phone) "
                      "VALUES (?,?,?,?,?,?,?,?)", (uid, uname, "pbkdf2$fake", role, name, center, active, "SENTINEL_PHONE"))
        for i, (model, typ) in enumerate([("Fiction Printer 1", "FDM"), ("Fiction Printer 2", "Resin"),
                                           ("Fiction Printer 3", "FDM"), ("Fiction Printer 4", None)], start=1):
            c.execute("INSERT INTO Devices (device_sn, customer_id, model, type) VALUES (?,?,?,?)",
                      (f"FAKE-SN-000{i}", 1, model, typ))
        t = [  # id, sn, center, status, tech, closed_at
            (101, "FAKE-SN-0001", 1, "New", None, None),                                # unassigned
            (102, "FAKE-SN-0002", 1, "In Repair", 11, None),
            (103, "FAKE-SN-0003", 1, "Waiting for Parts", 12, None),
            (104, "FAKE-SN-0004", 1, "Testing", 13, None),                              # assigned to inactive tech
            (105, "FAKE-SN-0001", 1, "Resolved/Closed", 11, "2026-10-12 09:00:00"),     # recent closure
            (106, "FAKE-SN-0002", 1, "Resolved/Closed", 11, "2026-09-01 09:00:00"),     # old closure
            (107, "FAKE-SN-0003", 1, "Resolved/Closed", 11, None),                      # legacy closed w/o time
            (108, "FAKE-SN-0004", 2, "In Repair", 31, None),                            # other branch
            (109, "FAKE-SN-0001", 1, "Diagnosing", 31, None),                           # center A job, tech of B
            (110, "FAKE-SN-0002", 1, "Diagnosing", 41, None),                           # tech without center
        ]
        for tid, sn, center, status, tech, closed in t:
            c.execute("INSERT INTO Tickets (ticket_id, device_sn, issue_category, description, center_id, status, "
                      "assigned_tech_id, created_at, closed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (tid, sn, "SENTINEL_ISSUE", "SENTINEL_NOTES", center, status, tech, "2026-10-01 08:00:00", closed))
        c.execute("INSERT INTO Spare_Parts (part_sku, part_name, stock_quantity) VALUES ('FAKE-SKU-1','Fiction Part',10)")
        c.execute("INSERT INTO Ticket_Status_History (ticket_id, from_status, to_status, changed_by, changed_at) "
                  "VALUES (102,'New','In Repair',11,'2026-10-02 10:00:00')")

    def mutate(self, sql, params=()):
        c = sqlite3.connect(self.path)
        c.execute(sql, params)
        c.commit()
        c.close()

    # -------------------------------------------------------------------------------- request helper
    def call(self, path=api.SNAPSHOT_PATH, *, method="GET", token=TOKEN, env=None, query="", get_conn=None,
             now_utc=NOW_UTC, headers=None):
        environ = {"PATH_INFO": path, "REQUEST_METHOD": method, "QUERY_STRING": query}
        if token is not None:
            environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        environ.update(headers or {})
        captured = {}

        def start_response(status, hdrs):
            captured["status"] = int(status.split()[0])
            captured["headers"] = dict(hdrs)

        def default_get_conn():
            conn = SqliteConn(self.path)
            self.conns.append(conn)
            return conn

        out, log = None, io.StringIO()
        with redirect_stdout(log):
            out = api.handle(environ, start_response, get_conn=get_conn or default_get_conn,
                             status_labels=STATUS_LABELS, config_env=_env() if env is None else env,
                             clock=lambda: (now_utc, NOW_LOCAL, 1_000_000.0))
        raw = b"".join(out).decode("utf-8")
        return captured["status"], captured["headers"], json.loads(raw), raw, log.getvalue()


class TestAuthAndScope(ApiTestCase):
    def test_valid_token_returns_only_center_a(self):
        status, hdrs, body, raw, _ = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(body["scope"], {"center_id": 1, "center_name": "Test Branch A"})
        self.assertTrue(all(j["center_id"] == 1 for j in body["jobs"]))
        self.assertTrue(all(t["center_id"] == 1 for t in body["technicians"]))
        self.assertNotIn(108, [j["ticket_id"] for j in body["jobs"]])           # other center's job
        self.assertNotIn("Other Branch Tech", raw)
        self.assertNotIn("No Center Tech", raw)
        self.assertTrue(body["complete"])

    def test_missing_and_invalid_credentials(self):
        s, h, b, raw, _ = self.call(token=None)
        self.assertEqual((s, b["error"]["code"]), (401, "authentication_required"))
        self.assertIn("Bearer", h["WWW-Authenticate"])
        s, _, b, _, _ = self.call(token="wrong-token")
        self.assertEqual((s, b["error"]["code"]), (401, "invalid_credentials"))
        s, _, b, _, _ = self.call(headers={"HTTP_AUTHORIZATION": "Basic abc"}, token=None)
        self.assertEqual(s, 401)
        s, _, b, _, _ = self.call(token="x" * 1000)
        self.assertEqual(s, 401)

    def test_revoked_and_rotated_tokens(self):
        both = _env(INTEGRATION_API_TOKEN_SHA256=f"{api.hash_token(OLD_TOKEN)},{api.hash_token(TOKEN)}")
        self.assertEqual(self.call(token=OLD_TOKEN, env=both)[0], 200)   # overlap window
        self.assertEqual(self.call(token=TOKEN, env=both)[0], 200)
        after = _env()                                                      # old hash removed = revoked
        self.assertEqual(self.call(token=OLD_TOKEN, env=after)[0], 401)
        self.assertEqual(self.call(token=TOKEN, env=after)[0], 200)

    def test_missing_or_bad_configuration_fails_closed(self):
        bad_envs = [
            {},                                                                          # nothing configured
            _env(INTEGRATION_API_CENTER_ID=None),                                        # no scope
            _env(INTEGRATION_API_CENTER_ID=""),
            _env(INTEGRATION_API_CENTER_ID="all"),                                       # no all-centers mode
            _env(INTEGRATION_API_CENTER_ID="*"),
            _env(INTEGRATION_API_CENTER_ID="1,2"),                                       # single center only
            _env(INTEGRATION_API_CENTER_ID="0"),
            _env(INTEGRATION_API_TOKEN_SHA256=None),
            _env(INTEGRATION_API_TOKEN_SHA256="not-a-hash"),
            _env(INTEGRATION_API_TOKEN_SHA256=",".join([api.hash_token(TOKEN)] * 3)),
            _env(INTEGRATION_API_DEVICE_REF_KEY="short"),
            _env(INTEGRATION_API_MAX_JOBS="abc"),                                        # set but invalid
            _env(INTEGRATION_API_CLOSED_WINDOW_DAYS="999"),
        ]
        for env in bad_envs:
            with self.subTest(env=env):
                s, _, b, raw, _ = self.call(env=env)
                self.assertEqual((s, b["error"]["code"]), (503, "integration_not_configured"))
                self.assertNotIn("jobs", b)
        # scope pointing at a center that does not exist
        s, _, b, _, _ = self.call(env=_env(INTEGRATION_API_CENTER_ID="999"))
        self.assertEqual((s, b["error"]["code"]), (503, "integration_not_configured"))

    def test_request_parameters_cannot_widen_scope(self):
        self.assertEqual(self.call(query="center_id=1")[0], 200)
        s, _, b, _, _ = self.call(query="center_id=2")
        self.assertEqual((s, b["error"]["code"]), (403, "scope_forbidden"))
        for q in ["center_id=all", "center_id=", "center_id=1&center_id=2", "center_id=-1", "center_id=1.0"]:
            with self.subTest(q=q):
                self.assertEqual(self.call(query=q)[0], 400)
        for q in ["all=1", "include_all=true", "token=" + TOKEN, "center_id=1&limit=9999", "access_token=" + TOKEN]:
            with self.subTest(q=q):
                s, _, b, raw, _ = self.call(query=q)
                self.assertEqual(s, 400)
                self.assertNotIn(TOKEN, raw)                                 # never echoed
        self.assertEqual(self.call(query="a=" + "x" * 300)[0], 400)
        self.assertEqual(self.call(query="%%%")[0], 400)

    def test_unknown_path_and_methods(self):
        self.assertEqual(self.call(path="/api/v1/office/nope")[0], 404)
        self.assertEqual(self.call(path="/api/v1/")[0], 404)
        for m in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            with self.subTest(m=m):
                s, h, b, _, _ = self.call(method=m)
                self.assertEqual((s, b["error"]["code"]), (405, "method_not_allowed"))
                self.assertEqual(h["Allow"], "GET")
                self.assertFalse([k for k in h if k.lower().startswith("access-control")])

    def test_failed_auth_throttle_does_not_lock_out_valid_token(self):
        env = _env(INTEGRATION_API_AUTH_FAIL_LIMIT_PER_MIN="3")
        codes = [self.call(token="bad", env=env)[0] for _ in range(5)]
        self.assertEqual(codes, [401, 401, 401, 429, 429])
        self.assertEqual(self.call(env=env)[0], 200)                 # attacker cannot starve the connector

    def test_valid_token_rate_limit(self):
        env = _env(INTEGRATION_API_RATE_LIMIT_PER_MIN="2")
        self.assertEqual([self.call(env=env)[0] for _ in range(3)], [200, 200, 429])
        s, h, b, _, _ = self.call(env=env)
        self.assertEqual((s, b["error"]["code"]), (429, "rate_limited"))
        self.assertTrue(int(h["Retry-After"]) >= 1)


class TestSnapshotContent(ApiTestCase):
    def test_minimal_fields_and_no_leaks(self):
        s, _, body, raw, _ = self.call()
        self.assertEqual(set(body), {"schema_version", "generated_at", "revision", "complete", "scope", "limits",
                                     "technicians", "jobs"})
        for t in body["technicians"]:
            self.assertEqual(set(t), {"user_id", "display_name", "role", "center_id", "is_active", "availability"})
        for j in body["jobs"]:
            self.assertEqual(set(j), {"ticket_id", "center_id", "status", "assigned_tech_id", "assignee_in_scope",
                                      "device", "closed_at"})
            self.assertEqual(set(j["device"]), {"ref", "model", "type"})
        for marker in SENTINELS:
            self.assertNotIn(marker, raw, marker)
        self.assertNotIn("pbkdf2", raw)
        self.assertNotIn(TOKEN, raw)

    def test_technician_selection_policy(self):
        _, _, body, _, _ = self.call()
        by_id = {t["user_id"]: t for t in body["technicians"]}
        self.assertEqual(sorted(by_id), [11, 12, 13, 15])           # lead included; inactive only if still assigned
        self.assertEqual(by_id[12]["role"], "technician_lead")
        self.assertFalse(by_id[13]["is_active"])
        self.assertTrue(by_id[15]["is_active"])                      # technician without any job is still listed
        for forbidden in (14, 20, 21, 31, 41):                       # inactive idle, customer, manager, other center
            self.assertNotIn(forbidden, by_id)
        self.assertTrue(all(t["availability"] == "unknown" for t in body["technicians"]))

    def test_job_selection_status_and_assignment(self):
        _, _, body, _, _ = self.call()
        jobs = {j["ticket_id"]: j for j in body["jobs"]}
        self.assertEqual(list(jobs), [101, 102, 103, 104, 105, 109, 110])   # deterministic order, ids ascending
        self.assertNotIn(106, jobs)                                          # closed before the window
        self.assertNotIn(107, jobs)                                          # closed without timestamp: excluded
        self.assertNotIn(108, jobs)                                          # other center
        self.assertEqual({k: v["status"] for k, v in jobs.items()},
                         {101: "New", 102: "In Repair", 103: "Waiting for Parts", 104: "Testing",
                          105: "Resolved/Closed", 109: "Diagnosing", 110: "Diagnosing"})   # source values untouched
        self.assertIsNone(jobs[101]["assigned_tech_id"])                      # unassigned stays null
        self.assertIsNone(jobs[101]["assignee_in_scope"])
        self.assertEqual(jobs[102]["assigned_tech_id"], 11)
        self.assertTrue(jobs[104]["assignee_in_scope"])                       # inactive assignee still resolvable
        self.assertEqual(jobs[105]["closed_at"], "2026-10-12 09:00:00")
        self.assertIsNone(jobs[102]["closed_at"])
        # assignee from another branch / without branch: id reported honestly, but flagged and not exported
        self.assertEqual(jobs[109]["assigned_tech_id"], 31)
        self.assertFalse(jobs[109]["assignee_in_scope"])
        self.assertFalse(jobs[110]["assignee_in_scope"])
        self.assertEqual(jobs[102]["device"]["model"], "Fiction Printer 2")
        self.assertEqual(jobs[102]["device"]["type"], "Resin")
        self.assertIsNone(jobs[104]["device"]["type"])

    def test_closed_window_is_explicit(self):
        ids = lambda **env: [j["ticket_id"] for j in self.call(env=_env(**env))[2]["jobs"]]
        self.assertIn(105, ids())                                              # 3 days ago, default window 7
        self.assertNotIn(105, ids(INTEGRATION_API_CLOSED_WINDOW_DAYS="0"))     # 0 = open jobs only
        self.mutate("UPDATE Tickets SET closed_at='2026-09-20 09:00:00' WHERE ticket_id=106")   # 25 days ago
        self.assertNotIn(106, ids())
        self.assertIn(106, ids(INTEGRATION_API_CLOSED_WINDOW_DAYS="31"))
        # boundary: cutoff is NOW_LOCAL - 7 days = 2026-10-08 12:00:00, inclusive
        self.mutate("UPDATE Tickets SET closed_at='2026-10-08 12:00:00' WHERE ticket_id=106")
        self.assertIn(106, ids())
        self.mutate("UPDATE Tickets SET closed_at='2026-10-08 11:59:59' WHERE ticket_id=106")
        self.assertNotIn(106, ids())
        self.assertEqual(self.call(env=_env(INTEGRATION_API_CLOSED_WINDOW_DAYS="31"))[2]["limits"]["closed_job_window_days"], 31)

    def test_device_reference_is_opaque_and_stable(self):
        _, _, a, raw, _ = self.call()
        _, _, b, _, _ = self.call()
        refs = {j["ticket_id"]: j["device"]["ref"] for j in a["jobs"]}
        self.assertEqual(refs, {j["ticket_id"]: j["device"]["ref"] for j in b["jobs"]})
        self.assertEqual(refs[101], refs[105])                                # same physical device -> same ref
        self.assertNotEqual(refs[101], refs[102])
        self.assertTrue(all(re.fullmatch(r"dev_[0-9a-f]{24}", r) for r in refs.values()))
        self.assertNotIn("FAKE-SN", raw)
        _, _, other, _, _ = self.call(env=_env(INTEGRATION_API_DEVICE_REF_KEY="another-fictional-key-0123456789abcdefghij"))
        self.assertNotEqual(refs[101], other["jobs"][0]["device"]["ref"])     # keyed, not a plain hash

    def test_thai_names_roundtrip(self):
        self.mutate("UPDATE Users SET name=? WHERE user_id=11", ("ช่างทดสอบ สมมติ",))
        _, hdrs, body, raw, _ = self.call()
        self.assertEqual({t["user_id"]: t["display_name"] for t in body["technicians"]}[11], "ช่างทดสอบ สมมติ")
        self.assertIn("charset=utf-8", hdrs["Content-Type"])

    def test_capabilities(self):
        s, _, body, _, _ = self.call(path=api.CAPABILITIES_PATH)
        self.assertEqual(s, 200)
        self.assertEqual(body["source_statuses"], list(STATUS_LABELS))
        self.assertEqual(body["status_labels_th"]["In Repair"], "กำลังซ่อม")
        self.assertFalse(body["semantics"]["assigned_means_accepted"])
        self.assertEqual(self.call(path=api.CAPABILITIES_PATH, token=None)[0], 401)
        self.assertEqual(self.call(path=api.CAPABILITIES_PATH, query="center_id=2")[0], 403)


class TestRevision(ApiTestCase):
    def rev(self, **kw):
        return self.call(**kw)[2]["revision"]

    def test_stable_when_nothing_changes_and_generated_at_is_ignored(self):
        a = self.call(now_utc=NOW_UTC)[2]
        b = self.call(now_utc=NOW_UTC + datetime.timedelta(hours=5))[2]
        self.assertNotEqual(a["generated_at"], b["generated_at"])
        self.assertEqual(a["revision"], b["revision"])
        self.assertEqual(a["generated_at"], "2026-10-15T05:00:00Z")
        self.assertRegex(a["revision"], r"^rev-[0-9a-f]{32}$")

    def test_changes_on_business_fields(self):
        base = self.rev()
        steps = [
            ("UPDATE Users SET name='Renamed Tester' WHERE user_id=11", ()),          # rename (id unchanged)
            ("UPDATE Tickets SET assigned_tech_id=15 WHERE ticket_id=101", ()),        # assignment
            ("UPDATE Tickets SET status='Testing' WHERE ticket_id=102", ()),           # status
            ("UPDATE Users SET is_active=0 WHERE user_id=15", ()),
            ("UPDATE Service_Centers SET name='Renamed Branch' WHERE center_id=1", ()),
        ]
        seen = {base}
        for sql, params in steps:
            self.mutate(sql, params)
            r = self.rev()
            self.assertNotIn(r, seen, sql)
            seen.add(r)

    def test_unrelated_changes_do_not_change_revision(self):
        base = self.rev()
        self.mutate("UPDATE Tickets SET description='changed notes', csat_comment='x' WHERE ticket_id=102")
        self.mutate("UPDATE Customers SET name='Renamed Customer' WHERE customer_id=1")
        self.mutate("UPDATE Spare_Parts SET stock_quantity=1")
        self.mutate("UPDATE Tickets SET status='Testing', assigned_tech_id=12 WHERE ticket_id=108")   # other center
        self.assertEqual(self.rev(), base)

    def test_renamed_staff_keep_stable_id(self):
        _, _, before, _, _ = self.call()
        self.mutate("UPDATE Users SET name='Completely Different' WHERE user_id=11")
        _, _, after, _, _ = self.call()
        job = lambda body: next(j for j in body["jobs"] if j["ticket_id"] == 102)
        self.assertEqual(job(before)["assigned_tech_id"], job(after)["assigned_tech_id"], 11)
        self.assertEqual({t["user_id"] for t in before["technicians"]}, {t["user_id"] for t in after["technicians"]})


class TestBoundsAndErrors(ApiTestCase):
    def test_too_many_jobs_is_an_explicit_error_not_truncation(self):
        s, _, b, raw, _ = self.call(env=_env(INTEGRATION_API_MAX_JOBS="5"))      # 7 qualifying jobs
        self.assertEqual((s, b["error"]["code"]), (413, "snapshot_too_large"))
        self.assertEqual(b["error"]["limit"], 5)
        self.assertNotIn("jobs", b)
        s, _, b, _, _ = self.call(env=_env(INTEGRATION_API_MAX_JOBS="7"))        # exactly at the limit is fine
        self.assertEqual((s, len(b["jobs"])), (200, 7))

    def test_database_connection_failure_is_sanitized(self):
        def broken():
            raise RuntimeError("could not connect: password=SECRETPW host=db.internal")
        s, h, b, raw, log = self.call(get_conn=broken)
        self.assertEqual((s, b["error"]["code"]), (503, "data_unavailable"))
        for text in (raw, log):
            self.assertNotIn("SECRETPW", text)
            self.assertNotIn("db.internal", text)

    def test_query_failure_is_sanitized(self):
        holder = {}

        def failing():
            holder["c"] = SqliteConn(self.path, fail_on="FROM Tickets")
            return holder["c"]
        s, h, b, raw, log = self.call(get_conn=failing)
        self.assertEqual((s, b["error"]["code"]), (500, "internal_error"))
        for text in (raw, log):
            self.assertNotIn("SECRETPW", text)
            self.assertNotIn("SELECT", text)
            self.assertNotIn("Traceback", text)
        self.assertTrue(holder["c"].closed)                                      # connection released on error

    def test_no_store_on_every_response_and_no_cors(self):
        cases = [self.call(), self.call(token=None), self.call(query="center_id=2"), self.call(path="/api/v1/x"),
                 self.call(method="POST"), self.call(env={}), self.call(path=api.CAPABILITIES_PATH)]
        for s, h, *_ in cases:
            with self.subTest(status=s):
                self.assertEqual(h["Cache-Control"], "no-store")
                self.assertEqual(h["X-Content-Type-Options"], "nosniff")
                self.assertTrue(h["Content-Type"].startswith("application/json"))
                self.assertFalse([k for k in h if k.lower().startswith("access-control")])

    def test_token_never_logged(self):
        logs = [self.call()[4], self.call(token="wrong-secret-token")[4], self.call(token=None)[4],
                self.call(get_conn=lambda: (_ for _ in ()).throw(RuntimeError("x")))[4]]
        for log in logs:
            self.assertNotIn(TOKEN, log)
            self.assertNotIn("wrong-secret-token", log)


class TestReadOnlyGuarantees(ApiTestCase):
    def test_snapshot_does_not_modify_anything(self):
        before = _dump(self.path)
        for _ in range(3):
            self.assertEqual(self.call()[0], 200)
        self.assertEqual(self.call(path=api.CAPABILITIES_PATH)[0], 200)
        self.assertEqual(_dump(self.path), before)           # stock, jobs, history, users, everything identical

    def test_snapshot_runs_in_read_only_transaction_and_only_selects(self):
        self.call()
        conn = self.conns[-1]
        self.assertTrue(conn.began)                           # begin_read_only_snapshot() called before queries
        self.assertTrue(conn.closed)
        self.assertTrue(conn.statements and all(s.lstrip().upper().startswith("SELECT") for s in conn.statements))
        # the double really refuses writes once the hook ran (mirrors PostgreSQL READ ONLY)
        c = SqliteConn(self.path)
        c.begin_read_only_snapshot()
        with self.assertRaises(sqlite3.OperationalError):
            c.execute("UPDATE Spare_Parts SET stock_quantity = 0")

    def test_sql_constants_contain_no_write_keywords_or_literals_that_break_placeholders(self):
        write = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO)\b", re.I)
        for sql in api.ALL_SQL:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            self.assertIsNone(write.search(sql), sql)
            self.assertNotIn("%", sql)                        # db._Conn rewrites "?" to "%s"
        self.assertEqual([s.count("?") for s in api.ALL_SQL], [1, 2, 3])

    def test_never_touches_stock_odoo_or_write_paths(self):
        src = _read("integration_api.py")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for forbidden in ("odoo_client", "import db", "Spare_Parts", "Service_Logs", "commit(", "executescript",
                          "_sync_", "approve", "deduct"):
            self.assertNotIn(forbidden, code, forbidden)


class TestCliAndWiring(unittest.TestCase):
    def test_generate_token_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(api._cli(["integration_api.py", "generate-token"]), 0)
        lines = buf.getvalue().splitlines()
        token = next(l for l in lines if l.startswith("tdsp_int_"))
        digest = next(l for l in lines if re.fullmatch(r"[0-9a-f]{64}", l))
        self.assertEqual(api.hash_token(token), digest)
        self.assertGreaterEqual(len(token), 40)

    def test_app_hook_and_container_packaging(self):
        app = _read("app.py")
        hook = app.index("integration_api.handle(")
        self.assertLess(hook, app.index("conn = db.get_conn()", app.index("def application(")))   # before session handling
        self.assertIn("/api/v1", app[hook - 400:hook])
        self.assertIn("integration_api.py", _read("Dockerfile"))
        compose = _read("docker-compose.yml")
        for name in ("INTEGRATION_API_TOKEN_SHA256", "INTEGRATION_API_CENTER_ID", "INTEGRATION_API_DEVICE_REF_KEY"):
            self.assertIn(name + "=${" + name + ":-}", compose)        # empty default = disabled = fail closed
        self.assertNotIn("tdsp_int_", compose + _read(".env.example"))


class TestAppEndToEnd(ApiTestCase):
    """Goes through app.application() itself (hook ordering, STATUS wiring, access-log redaction).
    Uses the real psycopg2 when installed, otherwise a tiny import-only stub from tests/_stubs; the
    database is still the isolated SQLite fixture (db.get_conn is replaced), never PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            sys.path.insert(0, os.path.join(ROOT, "tests", "_stubs"))
        try:
            import app as app_module
            import db as db_module
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"app.py could not be imported in this environment: {exc!r}")
        cls.app, cls.db = app_module, db_module

    def setUp(self):
        super().setUp()
        # The fixture has fixed closure dates; wall time must not age jobs out of this test.
        original_handle = api.handle
        def fixed_handle(*args, **kwargs):
            kwargs["clock"] = lambda: (NOW_UTC.replace(tzinfo=datetime.timezone.utc), NOW_LOCAL, 1000.0)
            return original_handle(*args, **kwargs)
        handle_patch = patch.object(api, "handle", side_effect=fixed_handle)
        handle_patch.start()
        self.addCleanup(handle_patch.stop)
        self._orig_get_conn = self.db.get_conn
        self.db.get_conn = lambda: SqliteConn(self.path)
        self._env_backup = {k: os.environ.get(k) for k in _env()}
        os.environ.update(_env())

    def tearDown(self):
        self.db.get_conn = self._orig_get_conn
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def req(self, path, token=TOKEN, method="GET", qs=""):
        environ = {"PATH_INFO": path, "REQUEST_METHOD": method, "QUERY_STRING": qs,
                   "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        cap = {}
        out = self.app.application(environ, lambda s, h: cap.update(status=int(s.split()[0]), headers=dict(h)))
        return cap["status"], cap["headers"], b"".join(out)

    def test_snapshot_and_capabilities_through_wsgi_app(self):
        s, h, b = self.req(api.SNAPSHOT_PATH)
        self.assertEqual(s, 200)
        self.assertEqual(h["Cache-Control"], "no-store")
        self.assertEqual(len(json.loads(b)["jobs"]), 7)
        s, _, b = self.req(api.CAPABILITIES_PATH)
        self.assertEqual(list(json.loads(b)["source_statuses"]), list(self.db.STATUSES))
        self.assertEqual(self.req(api.SNAPSHOT_PATH, token=None)[0], 401)
        self.assertEqual(self.req(api.SNAPSHOT_PATH, qs="center_id=2")[0], 403)

    def test_api_path_ignores_cookies_and_csrf_machinery(self):
        # POST with no CSRF token is answered by the API layer (405), not by the web CSRF check (403 HTML)
        s, h, b = self.req(api.SNAPSHOT_PATH, method="POST")
        self.assertEqual(s, 405)
        self.assertTrue(h["Content-Type"].startswith("application/json"))

    def test_regular_web_routes_unaffected(self):
        s, h, _ = self.req("/definitely-not-a-route", token=None)
        self.assertEqual(s, 404)
        self.assertTrue(h["Content-Type"].startswith("text/html"))

    def test_access_log_redacts_api_query_strings(self):
        handler = self.app.QuietWSGIRequestHandler.__new__(self.app.QuietWSGIRequestHandler)
        handler.client_address = ("127.0.0.1", 1)
        buf = io.StringIO()
        with redirect_stdout(buf):
            handler.log_message('"%s" %s %s', "GET /api/v1/office/snapshot?token=SECRETVALUE HTTP/1.1", "400", "-")
            handler.log_message('"%s" %s %s', "GET /track?sn=AB123 HTTP/1.1", "200", "-")
        out = buf.getvalue()
        self.assertNotIn("SECRETVALUE", out)
        self.assertIn("/api/v1/office/snapshot?[redacted]", out)
        self.assertIn("/track?sn=AB123", out)                       # non-API logging unchanged


if __name__ == "__main__":
    unittest.main()
