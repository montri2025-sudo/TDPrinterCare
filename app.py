# -*- coding: utf-8 -*-
"""
ระบบบริหารจัดการงานซ่อม (Repair Ticketing System) — prototype
รันด้วย Python มาตรฐาน (wsgiref) + SQLite + Jinja2 เท่านั้น ไม่ต้องพึ่ง framework ภายนอก
ใช้งาน:   python app.py   แล้วเปิด http://localhost:8000
"""
import contextvars
import datetime
import html
import hmac
import io
import json
import os
import re
import smtplib
import time
import uuid
import mimetypes
import zipfile
import urllib.error
import urllib.request
from collections import Counter
from email.mime.text import MIMEText
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse, urlencode
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
from socketserver import ThreadingMixIn

from jinja2 import Environment, FileSystemLoader, select_autoescape

import db
import odoo_client

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
PART_IMAGES_DIR = os.path.join(UPLOADS_DIR, "parts")

# ช่วงเวลานัดหมายที่เลือกได้ตอนจองคิวเข้ารับบริการ (แจ้งซ่อมออนไลน์แบบระบุวันนัด) — เวลาทำการ 09:00-17:00
# เว้นพักเที่ยง 12:00-13:00 — แก้ไขรายการนี้ได้โดยตรงถ้าต้องการเปลี่ยนช่วงเวลาทำการ
BOOKING_TIME_SLOTS = [
    "09:00-10:00", "10:00-11:00", "11:00-12:00",
    "13:00-14:00", "14:00-15:00", "15:00-16:00", "16:00-17:00",
]

MAX_IMAGES = 10
MAX_VIDEO_MB = 10
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024
MAX_PART_IMAGE_MB = 5
MAX_PART_IMAGE_BYTES = MAX_PART_IMAGE_MB * 1024 * 1024
MAX_PART_IMAGES = 9  # จำนวนรูปสูงสุดต่อสินค้า 1 ชิ้น (นับรวมรูปปกหลัก image_filename + รูปแกลเลอรี Part_Images)
MAX_SLIP_MB = 5
MAX_SLIP_BYTES = MAX_SLIP_MB * 1024 * 1024
MAX_DEVICE_PROOF_MB = 5
MAX_DEVICE_PROOF_BYTES = MAX_DEVICE_PROOF_MB * 1024 * 1024
DEVICE_PROOF_DIR = os.path.join(UPLOADS_DIR, "device_proof")  # หลักฐานการสั่งซื้อเครื่องพิมพ์ (รูปภาพ/PDF) แยกโฟลเดอร์ต่อเครื่อง
MAX_CENTER_LOGO_MB = 5
MAX_CENTER_LOGO_BYTES = MAX_CENTER_LOGO_MB * 1024 * 1024
MAX_CENTER_DOC_MB = 5
MAX_CENTER_DOC_BYTES = MAX_CENTER_DOC_MB * 1024 * 1024
CENTER_FILES_DIR = os.path.join(UPLOADS_DIR, "centers")  # โลโก้ + เอกสาร (หนังสือรับรอง/ภ.พ.20) ของศูนย์บริการ แยกโฟลเดอร์ต่อสาขา
MAX_RESOURCE_MB = 20
MAX_RESOURCE_BYTES = MAX_RESOURCE_MB * 1024 * 1024
MARKETING_DIR = os.path.join(UPLOADS_DIR, "marketing")  # โบรชัวร์/เอกสาร PDF ที่ HQ แชร์ให้ศูนย์บริการโปรโมท (วิดีโอใช้ลิงก์ภายนอก ไม่อัปโหลดไฟล์) — ตารางเดิม เก็บไว้เผื่อมีข้อมูลเก่า ไม่มีเมนูเข้าถึงแล้ว
MAX_ACTIVITY_FILE_MB = 100
MAX_ACTIVITY_FILE_BYTES = MAX_ACTIVITY_FILE_MB * 1024 * 1024
ACTIVITY_FILES_DIR = os.path.join(UPLOADS_DIR, "activities")  # ไฟล์แนบของโมดูล ShareSpace (Marketing/Technical) แยกโฟลเดอร์ต่อกิจกรรม
ACTIVITY_FILE_CONTENT_TYPES = (
    "image/", "video/", "application/pdf", "application/zip", "application/x-zip-compressed",
    "application/msword", "application/vnd.openxmlformats-officedocument", "application/vnd.ms-excel",
    "text/plain",
)

env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html"]),
)


def _file_icon(filename):
    """คืนอิโมจิไอคอนตามนามสกุลไฟล์ — ใช้แสดงในรายการไฟล์แนบของโมดูล ShareSpace"""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "svg"):
        return "🖼️"
    if ext == "pdf":
        return "📕"
    if ext in ("mp4", "mov", "avi", "webm", "mkv"):
        return "🎬"
    if ext in ("zip", "rar", "7z"):
        return "🗜️"
    if ext in ("doc", "docx"):
        return "📄"
    if ext in ("xls", "xlsx", "csv"):
        return "📊"
    return "📁"


env.filters["file_icon"] = _file_icon


def _asset_version(rel_path):
    """
    คืนเวลาที่ไฟล์ static แก้ไขล่าสุด (mtime) เพื่อใช้เป็น query string ต่อท้าย URL เช่น
    /static/style.css?v=1234567890 — บังคับให้เบราว์เซอร์/reverse proxy ดึงไฟล์ใหม่ทุกครั้งที่มีการแก้ไขเนื้อหา
    (มิฉะนั้นเบราว์เซอร์อาจแคช CSS/JS เก่าค้างไว้ ทำให้หน้าเว็บแสดงผลผิดเพี้ยนหลังอัปเดต)
    """
    fs_path = os.path.join(STATIC_DIR, rel_path)
    try:
        return int(os.path.getmtime(fs_path))
    except OSError:
        return 0


env.globals["asset_v"] = _asset_version

# session_token -> {"user_id", "csrf_token", "created", "last_seen"}
# (in-memory: รีสตาร์ทเซิร์ฟเวอร์แล้วต้อง login ใหม่ — ใช้ได้กับ deploy แบบ process เดียว
#  ถ้าจะสเกลเป็นหลาย process/instance ในอนาคต ควรย้ายไปเก็บใน Redis หรือฐานข้อมูลแทน)
SESSIONS = {}
SESSION_IDLE_TIMEOUT = 8 * 3600       # ไม่มีการใช้งานเกิน 8 ชม. -> หมดอายุ (ต้อง login ใหม่)
SESSION_ABSOLUTE_TIMEOUT = 24 * 3600  # อายุ session สูงสุด 24 ชม. ไม่ว่าจะใช้งานต่อเนื่องแค่ไหน

# ป้องกันการเดารหัสผ่านซ้ำๆ (brute force) — นับความพยายาม login ผิดต่อคู่ (IP, username)
LOGIN_ATTEMPTS = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW = 15 * 60    # นับเฉพาะความพยายามผิดภายใน 15 นาทีล่าสุด
LOGIN_LOCKOUT_SECONDS = 15 * 60   # ล็อกชั่วคราว 15 นาทีหลังพยายามผิดครบจำนวน

# ตั้งเป็น "0" เฉพาะตอนทดสอบผ่าน http ธรรมดา (ไม่มี HTTPS) — ค่าเริ่มต้น "1" จะส่ง cookie
# แบบ Secure (ส่งเฉพาะผ่าน HTTPS) ซึ่งจำเป็นสำหรับใช้งานจริงผ่าน reverse proxy ที่ทำ TLS ให้
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"

# เก็บ csrf_token ของ request ปัจจุบัน (ต่อ thread/ต่อ request) เพื่อให้ render() แนบเข้าไปใน
# ทุกหน้าได้อัตโนมัติ โดยไม่ต้องแก้ signature ของทุก route handler
_csrf_ctx = contextvars.ContextVar("csrf_token", default=None)

# จำนวนการแจ้งเตือน (Notifications) ที่ยังไม่อ่านของผู้ใช้ปัจจุบัน — คำนวณครั้งเดียวต่อ request ใน application()
# แล้วแนบเข้า render() อัตโนมัติเหมือน csrf_token ด้านบน เพื่อให้กระดิ่งแจ้งเตือนใน base.html ใช้ได้ทุกหน้าโดยไม่ต้อง
# แก้ทุก route handler ให้ query เอง
_notif_ctx = contextvars.ContextVar("unread_notif_count", default=0)

ROLE_HOME = {
    "customer": "/customer/dashboard",
    "admin": "/admin/dashboard",
    "technician": "/tech/tasks",
    "manager": "/manager/dashboard",
    "sales": "/sales/orders",
}


# ---------------------------------------------------------------- helpers --

class HttpError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class Redirect(Exception):
    def __init__(self, location):
        self.location = location


def render(template_name, **ctx):
    tmpl = env.get_template(template_name)
    html = tmpl.render(
        statuses=db.STATUSES, status_labels=db.STATUS_LABELS, status_icons=db.STATUS_ICONS,
        csrf_token=_csrf_ctx.get(), unread_notif_count=_notif_ctx.get(), **ctx,
    )
    return html.encode("utf-8")


def parse_cookies(environ):
    c = SimpleCookie()
    c.load(environ.get("HTTP_COOKIE", ""))
    return {k: v.value for k, v in c.items()}


def parse_post(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH", 0) or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if length else b""
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}


def safe_filename(name):
    """ตัด path และอักขระอันตรายออก เหลือแค่ชื่อไฟล์ที่ปลอดภัยสำหรับเก็บลงดิสก์"""
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "file"


def parse_multipart(environ):
    """
    Minimal multipart/form-data parser (RFC 2388) เขียนเองด้วย stdlib ล้วน — ไม่พึ่งโมดูล
    cgi ที่เลิกใช้แล้วและถูกถอดออกจาก Python 3.13 เพื่อให้ยังใช้ได้กับ Python เวอร์ชันใหม่ๆ

    คืนค่า (fields, files):
      fields: dict[str, str]  — ค่าฟิลด์ข้อความทั่วไป
      files:  dict[str, list[{"filename","content_type","data"}]]  — ไฟล์ที่อัปโหลด (จัดกลุ่มตามชื่อฟิลด์)
    ถ้า Content-Type ไม่ใช่ multipart จะ fallback ไปใช้ parse_post() ตามปกติ
    """
    content_type = environ.get("CONTENT_TYPE", "")
    if "multipart/form-data" not in content_type:
        return parse_post(environ), {}

    bm = re.search(r'boundary="?([^";]+)"?', content_type)
    if not bm:
        return {}, {}
    boundary = ("--" + bm.group(1)).encode("utf-8")

    try:
        length = int(environ.get("CONTENT_LENGTH", 0) or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if length else b""

    fields, files = {}, {}
    for raw_part in body.split(boundary):
        part = raw_part[2:] if raw_part.startswith(b"\r\n") else raw_part
        if not part or part.startswith(b"--"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        if content.endswith(b"\r\n"):
            content = content[:-2]

        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower().decode()] = v.strip().decode()

        disp = headers.get("content-disposition", "")
        name_m = re.search(r'name="([^"]*)"', disp)
        if not name_m:
            continue
        field_name = name_m.group(1)

        filename_m = re.search(r'filename="([^"]*)"', disp)
        if filename_m:
            filename = filename_m.group(1)
            if filename:  # ช่อง file input ที่ไม่ได้เลือกไฟล์ -> ข้าม
                files.setdefault(field_name, []).append({
                    "filename": filename,
                    "content_type": headers.get("content-type", "application/octet-stream"),
                    "data": content,
                })
        else:
            fields[field_name] = content.decode("utf-8", errors="replace")

    return fields, files


def _client_ip(environ):
    """IP ของผู้ใช้จริง — รองรับกรณีอยู่หลัง reverse proxy (nginx-proxy ฯลฯ) ที่ส่ง
    X-Forwarded-For มาให้ ใช้ IP ตัวแรกในรายการ (ตัวใกล้ผู้ใช้ที่สุด)"""
    fwd = environ.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return environ.get("REMOTE_ADDR", "unknown")


def _get_session(token):
    """คืนค่า session dict ถ้า token ยังไม่หมดอายุ — อัปเดต last_seen ให้อัตโนมัติ
    และลบทิ้งถ้าหมดอายุแล้ว (idle timeout หรือ absolute timeout)"""
    if not token:
        return None
    sess = SESSIONS.get(token)
    if not sess:
        return None
    now = time.time()
    if now - sess["created"] > SESSION_ABSOLUTE_TIMEOUT or now - sess["last_seen"] > SESSION_IDLE_TIMEOUT:
        SESSIONS.pop(token, None)
        return None
    sess["last_seen"] = now
    return sess


def get_current_user(environ, conn):
    cookies = parse_cookies(environ)
    token = cookies.get("sid")
    sess = _get_session(token)
    if not sess:
        return None
    row = conn.execute("SELECT * FROM Users WHERE user_id=?", (sess["user_id"],)).fetchone()
    if row and not row["is_active"]:
        # บัญชีถูกระงับระหว่างที่ยัง login ค้างอยู่ -> เด้งออกทันที
        SESSIONS.pop(token, None)
        return None
    return row


def require_login(user, *roles):
    if user is None:
        raise Redirect("/login")
    if roles and user["role"] not in roles:
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงหน้านี้")


def get_quotes_for_ticket(conn, ticket_id):
    """ใบเสนอราคาทั้งหมดของตั๋วนี้ พร้อมรายการย่อยและยอดรวม (ใหม่สุดก่อน)"""
    quotes = conn.execute(
        "SELECT * FROM Quotations WHERE ticket_id=? ORDER BY quote_id DESC", (ticket_id,)
    ).fetchall()
    result = []
    for q in quotes:
        items = conn.execute(
            "SELECT * FROM Quotation_Items WHERE quote_id=? ORDER BY item_id", (q["quote_id"],)
        ).fetchall()
        total = sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items)
        result.append({
            "quote_id": q["quote_id"], "created_at": q["created_at"], "notes": q["notes"],
            "line_items": items, "total": round(total, 2),
        })
    return result


def build_invoice(conn, ticket_id):
    """สรุปรายการซ่อม (จาก Service_Logs ที่อนุมัติ/ตัดสต็อกแล้ว) เป็นใบแจ้งหนี้ลูกค้า"""
    rows = conn.execute(
        """SELECT sl.*, p.part_name, p.cost_price FROM Service_Logs sl
           LEFT JOIN Spare_Parts p ON p.part_sku = sl.part_sku_used
           WHERE sl.ticket_id=? AND sl.approval_status IN ('auto','approved')
           ORDER BY sl.created_at""",
        (ticket_id,),
    ).fetchall()
    items = []
    total = 0.0
    for r in rows:
        is_claim = bool(r["is_claim"]) if r["part_sku_used"] else False
        # เคลมประกัน — ไม่คิดค่าอะไหล่ (ราคาอะไหล่ = 0 บาทเสมอ) แต่ยังคงคิดค่าบริการตามปกติ
        part_cost = 0 if is_claim else ((r["cost_price"] or 0) * (r["quantity_used"] or 0) if r["part_sku_used"] else 0)
        labor = r["labor_fee"] or 0
        line_total = part_cost + labor
        total += line_total
        items.append({
            "created_at": r["created_at"], "action": r["action_taken"] or "-",
            "part_name": r["part_name"], "part_cost": part_cost, "is_claim": is_claim,
            "labor_fee": labor, "line_total": line_total, "tech_notes": r["tech_notes"],
        })
    return items, round(total, 2)


def _repair_invoice_report_rows(conn, from_sql, to_sql, scope_center):
    """รายงานรายการซ่อมแยกตามใบแจ้งหนี้ (สำหรับหน้ารายงาน) — เอาเฉพาะตั๋วที่ปิดงานแล้ว (Resolved/Closed)
    ในช่วงวันที่ที่เลือก (นับจากวันที่ปิดงาน = วันที่ออกใบแจ้งหนี้) แต่ละใบประกอบด้วยรายการซ่อมย่อยทุกรายการ
    (ใช้ build_invoice() ตัวเดียวกับที่สร้างใบแจ้งหนี้จริงในหน้าตั๋ว/หน้าพิมพ์ เพื่อให้ยอดตรงกันเป๊ะ) พร้อมยอดรวมสุทธิท้ายใบ
    — ข้ามตั๋วที่ปิดงานแล้วแต่ไม่มีรายการซ่อมที่ตัดสต็อก/อนุมัติแล้วเลย (ไม่มีอะไรให้ออกใบแจ้งหนี้)"""
    center_cond = " AND t.center_id = ?" if scope_center else ""
    center_params = [scope_center] if scope_center else []
    ticket_rows = conn.execute(
        f"""SELECT t.ticket_id, t.closed_at, d.model, c.name AS customer_name, u.name AS tech_name,
                   t.invoice_recorded, t.invoice_recorded_at, ur.name AS invoice_recorded_by_name
            FROM Tickets t
            JOIN Devices d ON d.device_sn = t.device_sn
            JOIN Customers c ON c.customer_id = d.customer_id
            LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
            LEFT JOIN Users ur ON ur.user_id = t.invoice_recorded_by
            WHERE t.status = 'Resolved/Closed' AND t.closed_at BETWEEN ? AND ?{center_cond}
            ORDER BY t.closed_at DESC""",
        (from_sql, to_sql, *center_params),
    ).fetchall()
    result = []
    for t in ticket_rows:
        items, total = build_invoice(conn, t["ticket_id"])
        if not items:
            continue
        claim_count = sum(1 for it in items if it["is_claim"])
        if claim_count == 0:
            claim_status = "none"
        elif claim_count == len(items):
            claim_status = "all"
        else:
            claim_status = "partial"
        result.append({
            "ticket_id": t["ticket_id"], "closed_at": t["closed_at"], "model": t["model"],
            "customer_name": t["customer_name"], "tech_name": t["tech_name"] or "-",
            "log_items": items, "total": total, "claim_status": claim_status,
            "invoice_recorded": bool(t["invoice_recorded"]), "invoice_recorded_at": t["invoice_recorded_at"],
            "invoice_recorded_by_name": t["invoice_recorded_by_name"],
        })
    return result


def _ticket_report_rows(conn, from_sql, to_sql, scope_center):
    """รายงานการซ่อม (สำหรับหน้ารายงาน) — รายการตั๋วซ่อมทุกใบที่แจ้งในช่วงวันที่ที่เลือก (นับจากวันที่แจ้งซ่อม
    created_at) ไม่จำกัดเฉพาะตั๋วที่ปิดงานแล้วเหมือนรายงานใบแจ้งหนี้ด้านบน — ใช้แสดงตารางสรุป (วันที่/ชื่อเครื่อง/
    ปัญหา/ลูกค้า/สถานะ/ช่างผู้รับผิดชอบ) พร้อมข้อมูลเพิ่มเติมสำหรับ popup รายละเอียดเมื่อคลิกแถว"""
    center_cond = " AND t.center_id = ?" if scope_center else ""
    center_params = [scope_center] if scope_center else []
    rows = conn.execute(
        f"""SELECT t.ticket_id, t.created_at, t.closed_at, t.status, t.issue_category, t.description,
                   t.channel, t.booking_date, t.booking_time_slot,
                   d.model, d.device_sn, c.name AS customer_name, c.phone AS customer_phone,
                   u.name AS tech_name, sc.name AS center_name
            FROM Tickets t
            JOIN Devices d ON d.device_sn = t.device_sn
            JOIN Customers c ON c.customer_id = d.customer_id
            LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
            LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
            WHERE t.created_at BETWEEN ? AND ?{center_cond}
            ORDER BY t.created_at DESC""",
        (from_sql, to_sql, *center_params),
    ).fetchall()
    return [
        {
            "ticket_id": r["ticket_id"], "created_at": r["created_at"], "closed_at": r["closed_at"],
            "status": r["status"], "status_label": db.STATUS_LABELS.get(r["status"], r["status"]),
            "status_icon": db.STATUS_ICONS.get(r["status"], ""),
            "issue_category": r["issue_category"], "description": r["description"] or "-",
            "model": r["model"], "device_sn": r["device_sn"],
            "customer_name": r["customer_name"], "customer_phone": r["customer_phone"] or "-",
            "tech_name": r["tech_name"] or "— ยังไม่มอบหมาย —",
            "center_name": r["center_name"] or "-",
            "channel": r["channel"], "booking_date": r["booking_date"], "booking_time_slot": r["booking_time_slot"],
            # ประวัติการเปลี่ยนสถานะ — ใช้แสดง popup รายละเอียดในหน้ารายงานแบบเดียวกับหน้าติดตามงานซ่อมของลูกค้า
            # (การ์ดไล่สี + stepper ความคืบหน้า + ไทม์ไลน์) แทนตารางข้อความธรรมดา
            "status_history": _ticket_status_history(conn, r["ticket_id"]),
        }
        for r in rows
    ]


def user_can_view_ticket(conn, user, ticket_id):
    """ใครมีสิทธิ์ดูตั๋วนี้บ้าง: เจ้าของ(ลูกค้า), ช่างที่ได้รับมอบหมาย, admin (ทุกศูนย์),
    manager (เฉพาะตั๋วของศูนย์บริการที่ตัวเองสังกัด)"""
    if not user:
        return False
    row = conn.execute(
        """SELECT t.assigned_tech_id, t.center_id, d.customer_id FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not row:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "manager":
        return row["center_id"] is not None and row["center_id"] == user.get("center_id")
    if user["role"] == "technician" and row["assigned_tech_id"] == user["user_id"]:
        return True
    if user["role"] == "customer" and row["customer_id"] == user["customer_id"]:
        return True
    return False


def require_center_access(user, resource_center_id):
    """สำหรับ manager: บล็อกการเข้าถึง/แก้ไขข้อมูลของศูนย์บริการอื่น (403)
    resource_center_id=None ถือเป็นข้อมูลกลาง/ใช้ร่วมกันทุกสาขา อนุญาตเสมอ ไม่จำกัดผลกับ admin"""
    if user["role"] == "manager" and resource_center_id is not None:
        if resource_center_id != user.get("center_id"):
            raise HttpError(403, "คุณไม่มีสิทธิ์เข้าถึงข้อมูลของศูนย์บริการอื่น")


# --------------------------------------------------------- แจ้งชำระเงิน/ใบเสร็จ --

def get_payments_for_ticket(conn, ticket_id):
    """รายการแจ้งชำระเงินทั้งหมดของตั๋วนี้ พร้อมชื่อผู้แจ้ง/ผู้ตรวจสอบ (ใหม่สุดก่อน)"""
    return conn.execute(
        """SELECT p.*, un.name AS notified_by_name, uc.name AS confirmed_by_name
           FROM Payments p
           LEFT JOIN Users un ON un.user_id = p.notified_by
           LEFT JOIN Users uc ON uc.user_id = p.confirmed_by
           WHERE p.ticket_id=? ORDER BY p.payment_id DESC""",
        (ticket_id,),
    ).fetchall()


def save_payment_slip(ticket_id, file_info):
    """ตรวจสอบและบันทึกไฟล์รูปสลิปโอนเงิน 1 ไฟล์ — เก็บในโฟลเดอร์อัปโหลดเดียวกับตั๋วนี้
    (uploads/<ticket_id>/) เพื่อให้ใช้เส้นทาง /media/<ticket_id>/<filename> ที่มีอยู่แล้ว
    เสิร์ฟไฟล์และจำกัดสิทธิ์การเข้าถึงได้ทันทีโดยไม่ต้องเพิ่ม route ใหม่ คืนชื่อไฟล์ที่บันทึกจริง"""
    if not file_info or not file_info.get("filename"):
        raise ValueError("กรุณาแนบรูปสลิปการโอนเงิน")
    if not file_info["content_type"].startswith("image/"):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ไม่ใช่ไฟล์รูปภาพที่รองรับ")
    if len(file_info["data"]) > MAX_SLIP_BYTES:
        size_mb = round(len(file_info["data"]) / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์รูปขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_SLIP_MB} MB)")
    ticket_dir = os.path.join(UPLOADS_DIR, str(ticket_id))
    os.makedirs(ticket_dir, exist_ok=True)
    stored = f"slip_{uuid.uuid4().hex[:8]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(ticket_dir, stored), "wb") as out:
        out.write(file_info["data"])
    return stored


def save_device_proof(device_sn, file_info):
    """บันทึกไฟล์หลักฐานการสั่งซื้อเครื่องพิมพ์ 1 ไฟล์ (รูปภาพหรือ PDF เท่านั้น) — ไม่บังคับแนบ
    คืน None ถ้าไม่ได้เลือกไฟล์เลย (ไม่ใช่ error) หรือคืนชื่อไฟล์ที่บันทึกจริงถ้าแนบและผ่านการตรวจสอบแล้ว
    เก็บแยกโฟลเดอร์ต่อเครื่อง (ตาม device_sn ที่ทำความสะอาดแล้ว กันอักขระอันตราย/path traversal)"""
    if not file_info or not file_info.get("filename"):
        return None
    content_type = file_info.get("content_type", "")
    if not (content_type.startswith("image/") or content_type == "application/pdf"):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ต้องเป็นรูปภาพหรือ PDF เท่านั้น")
    if len(file_info["data"]) > MAX_DEVICE_PROOF_BYTES:
        size_mb = round(len(file_info["data"]) / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์ขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_DEVICE_PROOF_MB} MB)")
    sn_dir = os.path.join(DEVICE_PROOF_DIR, safe_filename(device_sn))
    os.makedirs(sn_dir, exist_ok=True)
    stored = f"proof_{uuid.uuid4().hex[:8]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(sn_dir, stored), "wb") as out:
        out.write(file_info["data"])
    return stored


def save_center_logo(center_id, file_info):
    """บันทึกโลโก้สาขา 1 ไฟล์ (รูปภาพเท่านั้น เพราะแสดงบนหน้าแรกสาธารณะด้วย) คืน None ถ้าไม่ได้แนบไฟล์มา"""
    if not file_info or not file_info.get("filename"):
        return None
    if not file_info["content_type"].startswith("image/"):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ต้องเป็นไฟล์รูปภาพเท่านั้น (โลโก้แสดงบนหน้าแรกสาธารณะ)")
    if len(file_info["data"]) > MAX_CENTER_LOGO_BYTES:
        size_mb = round(len(file_info["data"]) / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์โลโก้ขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_CENTER_LOGO_MB} MB)")
    center_dir = os.path.join(CENTER_FILES_DIR, str(center_id))
    os.makedirs(center_dir, exist_ok=True)
    stored = f"logo_{uuid.uuid4().hex[:8]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(center_dir, stored), "wb") as out:
        out.write(file_info["data"])
    return stored


def save_center_document(center_id, file_info, prefix):
    """บันทึกไฟล์เอกสารประจำสาขา 1 ไฟล์ (รูปภาพหรือ PDF) เช่น หนังสือรับรองบริษัท/ภ.พ.20 —
    prefix กันชื่อไฟล์ชนกันระหว่างเอกสารคนละประเภทของศูนย์เดียวกัน คืน None ถ้าไม่ได้แนบไฟล์มา"""
    if not file_info or not file_info.get("filename"):
        return None
    content_type = file_info.get("content_type", "")
    if not (content_type.startswith("image/") or content_type == "application/pdf"):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ต้องเป็นรูปภาพหรือ PDF เท่านั้น")
    if len(file_info["data"]) > MAX_CENTER_DOC_BYTES:
        size_mb = round(len(file_info["data"]) / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์ขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_CENTER_DOC_MB} MB)")
    center_dir = os.path.join(CENTER_FILES_DIR, str(center_id))
    os.makedirs(center_dir, exist_ok=True)
    stored = f"{prefix}_{uuid.uuid4().hex[:8]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(center_dir, stored), "wb") as out:
        out.write(file_info["data"])
    return stored


def _delete_center_file(center_id, filename):
    """ลบไฟล์โลโก้/เอกสารเดิมของศูนย์บริการออกจากดิสก์ — เรียกตอนอัปโหลดไฟล์ใหม่แทนที่ไฟล์เดิม หรือตอนกด
    ลบไฟล์ทิ้งเฉยๆ เงียบๆ ไม่ error ถ้าไฟล์ไม่มีอยู่แล้ว (เผื่อกดซ้ำ/ข้อมูลไฟล์เพี้ยน)"""
    if not filename:
        return
    center_dir = os.path.abspath(os.path.join(CENTER_FILES_DIR, str(center_id)))
    fs_path = os.path.join(center_dir, filename)
    if os.path.abspath(fs_path).startswith(center_dir) and os.path.isfile(fs_path):
        try:
            os.remove(fs_path)
        except OSError:
            pass


def save_marketing_file(file_info):
    """บันทึกไฟล์ทรัพยากรโปรโมท 1 ไฟล์ (รูปภาพหรือ PDF เท่านั้น — ใช้กับประเภท Brochure/Document
    ส่วนประเภท Video ใช้ video_url ไม่มีไฟล์) คืน None ถ้าไม่ได้แนบไฟล์มา"""
    if not file_info or not file_info.get("filename"):
        return None
    content_type = file_info.get("content_type", "")
    if not (content_type.startswith("image/") or content_type == "application/pdf"):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ต้องเป็นรูปภาพหรือ PDF เท่านั้น")
    if len(file_info["data"]) > MAX_RESOURCE_BYTES:
        size_mb = round(len(file_info["data"]) / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์ขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_RESOURCE_MB} MB)")
    os.makedirs(MARKETING_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex[:8]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(MARKETING_DIR, stored), "wb") as out:
        out.write(file_info["data"])
    return stored


def _delete_marketing_file(filename):
    """ลบไฟล์ทรัพยากรโปรโมทเดิมออกจากดิสก์ — เงียบๆ ไม่ error ถ้าไฟล์ไม่มีอยู่แล้ว"""
    if not filename:
        return
    marketing_dir = os.path.abspath(MARKETING_DIR)
    fs_path = os.path.join(marketing_dir, filename)
    if os.path.abspath(fs_path).startswith(marketing_dir) and os.path.isfile(fs_path):
        try:
            os.remove(fs_path)
        except OSError:
            pass


# --------------------------------------------------------------------- ShareSpace --

def save_activity_file(file_info):
    """บันทึกไฟล์แนบของกิจกรรม ShareSpace 1 ไฟล์ (รูปภาพ/PDF/วิดีโอ/ZIP/เอกสาร Office) รองรับหลากหลายประเภท
    มากกว่าทรัพยากรโปรโมทเดิม เพราะกิจกรรมเดียวอาจมีทั้งภาพสินค้า โบรชัวร์ วิดีโอโปรโมท และไฟล์ ZIP รวมสื่อ
    คืน (stored_name, size_bytes) — คืน None ถ้าไม่ได้แนบไฟล์มา"""
    if not file_info or not file_info.get("filename"):
        return None
    content_type = file_info.get("content_type", "") or ""
    if not any(content_type.startswith(t) for t in ACTIVITY_FILE_CONTENT_TYPES):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' เป็นชนิดไฟล์ที่ไม่รองรับ (รองรับรูปภาพ/PDF/วิดีโอ/ZIP/เอกสาร)")
    size = len(file_info["data"])
    if size > MAX_ACTIVITY_FILE_BYTES:
        size_mb = round(size / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_ACTIVITY_FILE_MB} MB)")
    os.makedirs(ACTIVITY_FILES_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex[:10]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(ACTIVITY_FILES_DIR, stored), "wb") as out:
        out.write(file_info["data"])
    return stored, size


def _delete_activity_file(stored_name):
    """ลบไฟล์แนบกิจกรรมออกจากดิสก์ — เงียบๆ ไม่ error ถ้าไฟล์ไม่มีอยู่แล้ว"""
    if not stored_name:
        return
    activity_dir = os.path.abspath(ACTIVITY_FILES_DIR)
    fs_path = os.path.join(activity_dir, stored_name)
    if os.path.abspath(fs_path).startswith(activity_dir) and os.path.isfile(fs_path):
        try:
            os.remove(fs_path)
        except OSError:
            pass


def _activity_with_files(conn, activity_id):
    """โหลดกิจกรรม 1 รายการ พร้อมไฟล์แนบจัดกลุ่มตามหมวด (marketing/technical) เรียงใหม่สุดก่อนในแต่ละหมวด
    คืน None ถ้าไม่พบกิจกรรม"""
    activity = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not activity:
        return None
    file_rows = conn.execute(
        "SELECT * FROM Activity_Files WHERE activity_id=? ORDER BY uploaded_at DESC", (activity_id,)
    ).fetchall()
    activity = dict(activity)
    activity["marketing_files"] = [f for f in file_rows if f["category"] == "marketing"]
    activity["technical_files"] = [f for f in file_rows if f["category"] == "technical"]
    return activity


def _user_can_view_activity_category(user, category):
    """สิทธิ์การเข้าถึงไฟล์ ShareSpace ตามหมวด: 'marketing' — admin/manager/sales เห็นได้,
    'technical' — admin/technician เท่านั้น"""
    if not user:
        return False
    if user["role"] == "admin":
        return True
    if category == "marketing":
        return user["role"] in ("manager", "sales")
    if category == "technical":
        return user["role"] == "technician"
    return False


def _add_years(d, years):
    """บวก/ลบจำนวนปีให้วันที่ (datetime.date) แบบตรงปีปฏิทิน — ถ้าตกที่ 29 ก.พ. แล้วปีปลายทางไม่ใช่ปีอธิกสุรทิน
    จะปัดเป็น 28 ก.พ. แทน (เหมือนกับตรรกะ addYears() ฝั่ง JavaScript ในฟอร์มลงทะเบียนเครื่องพิมพ์)"""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _parse_date_or_none(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _ticket_detail_url_for(user, ticket_id):
    """ลิงก์กลับไปหน้ารายละเอียดตั๋วที่ถูกต้องตามบทบาทของผู้ใช้ (ใช้ redirect หลังยืนยัน/ปฏิเสธการชำระเงิน)"""
    if user["role"] in ("admin", "manager"):
        return f"/admin/ticket/{ticket_id}"
    if user["role"] == "technician":
        return f"/tech/ticket/{ticket_id}"
    return f"/customer/ticket/{ticket_id}"


def _require_staff_can_manage_payment(conn, user, ticket_id):
    """ยืนยัน/ปฏิเสธการแจ้งชำระเงินได้เฉพาะ staff (admin/manager/ช่างที่ได้รับมอบหมาย) เท่านั้น —
    ลูกค้าเห็นสถานะได้แต่กดยืนยันเงินของตัวเองไม่ได้ (ป้องกันแจ้งเท็จ)"""
    if not user or user["role"] == "customer":
        raise HttpError(403, "ไม่มีสิทธิ์ดำเนินการนี้")
    if not user_can_view_ticket(conn, user, ticket_id):
        raise HttpError(403, "ไม่มีสิทธิ์ดำเนินการนี้")


def days_left(warranty_end_date):
    import datetime
    try:
        end = datetime.datetime.strptime(warranty_end_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (end - datetime.date.today()).days


# สีหมุด/ป้ายกำกับตามประเภทเครื่องพิมพ์ที่ศูนย์บริการรับซ่อม
CENTER_TYPE_COLORS = {
    "both": "#8e44ad",   # ม่วง — รับทั้ง FDM และ Resin
    "fdm": "#2e5395",    # น้ำเงิน — รับเฉพาะ FDM
    "resin": "#e67e22",  # ส้ม — รับเฉพาะ Resin
    "none": "#888888",   # เทา — ยังไม่ระบุประเภทที่รับซ่อม
}
CENTER_TYPE_LABELS = {
    "both": "FDM + Resin",
    "fdm": "FDM เท่านั้น",
    "resin": "Resin เท่านั้น",
    "none": "ยังไม่ระบุประเภท",
}


def annotate_centers(centers):
    """เติม type_key / type_label / marker_color ให้แถวศูนย์บริการแต่ละแถว
    ตาม supports_fdm/supports_resin เพื่อให้ template ใช้แสดงป้ายกำกับและ
    เลือกสีหมุดบนแผนที่ได้โดยไม่ต้องคำนวณเองใน Jinja"""
    out = []
    for c in centers:
        c = dict(c)
        fdm = bool(c.get("supports_fdm"))
        resin = bool(c.get("supports_resin"))
        key = "both" if (fdm and resin) else "fdm" if fdm else "resin" if resin else "none"
        c["type_key"] = key
        if key == "none" and c.get("sells_products"):
            # ศูนย์ที่ไม่รับซ่อมเลยแต่เปิดขายสินค้า ถือเป็น "ขายอย่างเดียว" ไม่ใช่กรณียังไม่ได้ตั้งค่า
            c["type_label"] = "ขายสินค้าอย่างเดียว (ไม่รับซ่อม)"
        else:
            c["type_label"] = CENTER_TYPE_LABELS[key]
        c["marker_color"] = CENTER_TYPE_COLORS[key]
        out.append(c)
    return out


def _map_center_popup(c, overview_for_center):
    """สร้าง HTML สำหรับ popup ของหมุดศูนย์บริการบนแผนที่ภายใน (คลิกแล้วเห็นรายละเอียดศูนย์ทันที
    แทนที่จะเป็นแค่ชื่อ/ที่อยู่แบบเดิม)"""
    esc = html.escape
    lines = [f"<b>{esc(c['name'])}</b>"]
    if c.get("address"):
        lines.append(esc(c["address"]))
    if c.get("phone"):
        lines.append("☎ " + esc(c["phone"]))
    lines.append(f"<b>รับซ่อม: {esc(c['type_label'])}</b>")
    if c.get("sells_products"):
        lines.append('<b style="color:#b8860b;">จำหน่ายสินค้า</b>')

    ov = overview_for_center or {}
    managers = ov.get("managers") or []
    lines.append("<u>ผู้จัดการ:</u> " + (", ".join(esc(x["name"]) for x in managers) if managers else "— ยังไม่ได้กำหนด —"))
    sales_people = ov.get("sales_people") or []
    lines.append("<u>เซล:</u> " + (", ".join(esc(x["name"]) for x in sales_people) if sales_people else "— ไม่มี —"))
    technicians = ov.get("technicians") or []
    lines.append("<u>ทีมช่าง:</u> " + (", ".join(esc(x["name"]) for x in technicians) if technicians else "— ไม่มี —"))

    queue = ov.get("queue") or []
    if queue:
        lines.append(f"<u>คิวงานซ่อมปัจจุบัน ({len(queue)} รายการ):</u>")
        for tk in queue[:8]:
            status_label = db.STATUS_LABELS.get(tk["status"], tk["status"])
            lines.append(f"#{tk['ticket_id']} {esc(tk['model'])} — {esc(tk['customer_name'])} — {esc(status_label)}")
        if len(queue) > 8:
            lines.append(f"...และอีก {len(queue) - 8} รายการ")
    else:
        lines.append("ไม่มีงานในคิวขณะนี้")

    return "<br>".join(lines)


def _map_customer_popup(cu, devices):
    """สร้าง HTML สำหรับ popup ของหมุดลูกค้าบนแผนที่ภายใน (คลิกแล้วเห็นเครื่องพิมพ์ทั้งหมดของลูกค้า
    พร้อมสถานะการซ่อมล่าสุดของแต่ละเครื่อง)"""
    esc = html.escape
    lines = [f"<b>{esc(cu['name'])}</b>", f"เครื่องพิมพ์ทั้งหมด: {len(devices)} เครื่อง"]
    if devices:
        lines.append("<u>รายการเครื่องและสถานะซ่อมล่าสุด:</u>")
        for d in devices:
            if d["latest_status"]:
                status_label = db.STATUS_LABELS.get(d["latest_status"], d["latest_status"])
                status_text = f"#{d['latest_ticket_id']} {esc(status_label)}"
            else:
                status_text = "ยังไม่เคยแจ้งซ่อม"
            lines.append(f"{esc(d['model'])} ({esc(d['device_sn'])}) — {status_text}")
    else:
        lines.append("ยังไม่มีเครื่องพิมพ์ในระบบ")
    return "<br>".join(lines)


def _center_overview_map(conn, center_ids):
    """ข้อมูลผู้จัดการ/เซล/ทีมช่าง/คิวงานซ่อมปัจจุบัน ต่อศูนย์บริการ (สำหรับ popup บนแผนที่ Dashboard ภายใน
    ต่างจาก public_center_overview ตรงที่นี่แสดงชื่อลูกค้าในคิวงานได้ เพราะเป็นหน้าสำหรับ staff เท่านั้น)"""
    overview = {}
    for cid in center_ids:
        managers = conn.execute(
            "SELECT name FROM Users WHERE role='manager' AND center_id=? AND is_active=1 ORDER BY name", (cid,)
        ).fetchall()
        sales_people = conn.execute(
            "SELECT name FROM Users WHERE role='sales' AND center_id=? AND is_active=1 ORDER BY name", (cid,)
        ).fetchall()
        technicians = conn.execute(
            "SELECT name FROM Users WHERE role='technician' AND center_id=? AND is_active=1 ORDER BY name", (cid,)
        ).fetchall()
        queue = conn.execute(
            """SELECT t.ticket_id, t.status, d.model, c.name AS customer_name
               FROM Tickets t JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.center_id=? AND t.status != 'Resolved/Closed'
               ORDER BY t.created_at""",
            (cid,),
        ).fetchall()
        overview[cid] = {"managers": managers, "sales_people": sales_people,
                          "technicians": technicians, "queue": queue}
    return overview


def _customer_devices_map(conn, customer_ids):
    """รายการเครื่องพิมพ์ทั้งหมดของลูกค้าแต่ละราย พร้อมสถานะการซ่อมล่าสุดของแต่ละเครื่อง
    (สำหรับ popup บนแผนที่ Dashboard ภายใน)"""
    overview = {}
    for cust_id in customer_ids:
        devices = conn.execute(
            "SELECT device_sn, model FROM Devices WHERE customer_id=? ORDER BY device_sn", (cust_id,)
        ).fetchall()
        dev_list = []
        for d in devices:
            latest = conn.execute(
                "SELECT ticket_id, status FROM Tickets WHERE device_sn=? ORDER BY created_at DESC LIMIT 1",
                (d["device_sn"],),
            ).fetchone()
            dev_list.append({
                "device_sn": d["device_sn"], "model": d["model"],
                "latest_status": latest["status"] if latest else None,
                "latest_ticket_id": latest["ticket_id"] if latest else None,
            })
        overview[cust_id] = dev_list
    return overview


def report_date_range(environ):
    """อ่านช่วงวันที่จาก query string (?from=YYYY-MM-DD&to=YYYY-MM-DD) สำหรับหน้ารายงาน
    ค่าเริ่มต้นคือ 30 วันล่าสุด (รวมวันนี้) — คืนค่า (from_sql, to_sql, from_display, to_display)
    โดย from_sql/to_sql ครอบคลุมทั้งวัน (00:00:00 ถึง 23:59:59) พร้อมใช้เทียบกับคอลัมน์ created_at/closed_at
    ที่เก็บเป็น TEXT รูปแบบ 'YYYY-MM-DD HH:MM:SS'"""
    import datetime
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    today = datetime.date.today()
    default_from = today - datetime.timedelta(days=30)

    def _parse(raw, fallback):
        try:
            return datetime.datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return fallback

    from_d = _parse(qs.get("from", [""])[0], default_from)
    to_d = _parse(qs.get("to", [""])[0], today)
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    from_sql = from_d.strftime("%Y-%m-%d") + " 00:00:00"
    to_sql = to_d.strftime("%Y-%m-%d") + " 23:59:59"
    return from_sql, to_sql, from_d.strftime("%Y-%m-%d"), to_d.strftime("%Y-%m-%d")


def month_date_range(environ):
    """อ่านช่วงวันที่จาก query string (?from=YYYY-MM-DD&to=YYYY-MM-DD) — ใช้ร่วมกันได้ทุกหน้าที่ต้องการ
    ค่าเริ่มต้นเป็น "เดือนปัจจุบัน" (วันที่ 1 ถึงวันสุดท้ายของเดือนนี้) เช่น Kanban Board, รายการขายสินค้า
    คืนค่า (from_sql, to_sql, from_display, to_display) — รูปแบบเดียวกับ report_date_range() แต่ค่าเริ่มต้น
    เป็น "เดือนนี้" แทน "30 วันล่าสุด" """
    import datetime
    import calendar
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    today = datetime.date.today()
    default_from = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    default_to = today.replace(day=last_day)

    def _parse(raw, fallback):
        try:
            return datetime.datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return fallback

    from_d = _parse(qs.get("from", [""])[0], default_from)
    to_d = _parse(qs.get("to", [""])[0], default_to)
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    from_sql = from_d.strftime("%Y-%m-%d") + " 00:00:00"
    to_sql = to_d.strftime("%Y-%m-%d") + " 23:59:59"
    return from_sql, to_sql, from_d.strftime("%Y-%m-%d"), to_d.strftime("%Y-%m-%d")


def days_date_range(environ, default_days=15):
    """อ่านช่วงวันที่จาก query string (?from=YYYY-MM-DD&to=YYYY-MM-DD) เหมือน month_date_range() แต่ค่าเริ่มต้น
    เป็น "N วันล่าสุด" (นับรวมวันนี้) แทน "เดือนปัจจุบัน" — ใช้กับหน้า Dashboard สรุปภาพรวม (ค่าเริ่มต้น 15 วัน)
    คืนค่า (from_sql, to_sql, from_display, to_display)"""
    import datetime
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    today = datetime.date.today()
    default_from = today - datetime.timedelta(days=default_days - 1)
    default_to = today

    def _parse(raw, fallback):
        try:
            return datetime.datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return fallback

    from_d = _parse(qs.get("from", [""])[0], default_from)
    to_d = _parse(qs.get("to", [""])[0], default_to)
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    from_sql = from_d.strftime("%Y-%m-%d") + " 00:00:00"
    to_sql = to_d.strftime("%Y-%m-%d") + " 23:59:59"
    return from_sql, to_sql, from_d.strftime("%Y-%m-%d"), to_d.strftime("%Y-%m-%d")


DASHBOARD_TREND_MONTHS = 6  # จำนวนเดือนย้อนหลังที่แสดงในกราฟเส้นบนสุดของหน้า Dashboard (รวมเดือนปัจจุบัน)


def _last_n_months_labels(n):
    """คืน list ป้ายเดือนย้อนหลัง n เดือนจากเดือนปัจจุบัน (รวมเดือนนี้) รูปแบบ 'YYYY-MM' เรียงเก่า -> ใหม่"""
    import datetime
    today = datetime.date.today()
    labels = []
    y, mth = today.year, today.month
    for i in range(n - 1, -1, -1):
        mm = mth - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        labels.append(f"{yy:04d}-{mm:02d}")
    return labels


def _monthly_sum(rows, date_field, value_field, labels):
    """รวมค่า value_field ต่อเดือน (ตัด 7 ตัวแรกของ date_field เป็น YYYY-MM) จัดเรียงตาม labels ที่กำหนด
    ใช้วิธีตัด string แทนฟังก์ชันวันที่เฉพาะฐานข้อมูล เพื่อให้ทำงานเหมือนกันทั้ง SQLite (ทดสอบ) และ MySQL (จริง)"""
    totals = {lbl: 0 for lbl in labels}
    for r in rows:
        month = (r[date_field] or "")[:7]
        if month in totals:
            totals[month] += r[value_field] or 0
    return [totals[l] for l in labels]


def _monthly_count(rows, date_field, labels):
    """นับจำนวนแถวต่อเดือน (ตัด 7 ตัวแรกของ date_field เป็น YYYY-MM) จัดเรียงตาม labels ที่กำหนด"""
    totals = {lbl: 0 for lbl in labels}
    for r in rows:
        month = (r[date_field] or "")[:7]
        if month in totals:
            totals[month] += 1
    return [totals[l] for l in labels]


# ------------------------------------------------------------- route defs --

ROUTES = []  # (method, compiled_regex, handler)


def route(method, pattern):
    regex = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, regex, fn))
        return fn

    return deco


# --------------------------------------------------------------- auth ----

@route("GET", r"/")
def home(environ, m, conn, user):
    if user:
        raise Redirect(ROLE_HOME[user["role"]])
    return render("home.html", **public_center_overview(conn))


def public_center_overview(conn):
    """รวบรวมข้อมูลศูนย์บริการทั้งหมดสำหรับหน้าแรกสาธารณะ (ไม่ต้อง login)
    ต่อศูนย์: ผู้จัดการ, เซล, ทีมช่างทั้งหมด (ไม่แสดงเบอร์โทรส่วนตัวของพนักงานต่อสาธารณะ),
    คิวงานซ่อมที่ยังไม่ปิด (ไม่แสดงข้อมูลลูกค้า), และสินค้าที่จำหน่าย (ไม่รวมหมวด "อะไหล่" ที่ใช้เฉพาะงานซ่อมภายใน
    ไม่แสดงจำนวนคงเหลือ/ค่าคอมมิชชั่น/ราคา — ให้ลูกค้าดูรายละเอียดสินค้าใน popup สอบถามสินค้า
    พร้อมช่องทางติดต่อสาขาเพื่อขอใบเสนอราคาอย่างเป็นทางการ)"""
    centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall())
    centers_with_geo = [c for c in centers if c["latitude"] is not None and c["longitude"] is not None]
    # ใช้เปิด modal สอบถาม/ขอใบเสนอราคาสินค้า — ให้ข้อมูลติดต่อสาขา (เบอร์กลางของสาขา ไม่ใช่เบอร์ส่วนตัวพนักงาน)
    centers_contact_for_js = [
        {"id": c["center_id"], "name": c["name"], "phone": c["phone"] or "", "address": c["address"] or ""}
        for c in centers
    ]

    overview = {}
    for c in centers:
        cid = c["center_id"]
        managers = conn.execute(
            "SELECT name FROM Users WHERE role='manager' AND center_id=? AND is_active=1 ORDER BY name",
            (cid,),
        ).fetchall()
        sales_people = conn.execute(
            "SELECT name FROM Users WHERE role='sales' AND center_id=? AND is_active=1 ORDER BY name",
            (cid,),
        ).fetchall()
        technicians = conn.execute(
            "SELECT name FROM Users WHERE role='technician' AND center_id=? AND is_active=1 ORDER BY name",
            (cid,),
        ).fetchall()
        queue = conn.execute(
            """SELECT t.ticket_id, t.status, t.issue_category, d.model
               FROM Tickets t JOIN Devices d ON d.device_sn = t.device_sn
               WHERE t.center_id = ? AND t.status != 'Resolved/Closed'
               ORDER BY t.created_at""",
            (cid,),
        ).fetchall()
        parts_raw = conn.execute(
            "SELECT part_sku, part_name, category, image_filename, description FROM Spare_Parts "
            "WHERE (center_id=? OR center_id IS NULL) AND category != 'Spare_Part' ORDER BY part_name",
            (cid,),
        ).fetchall()
        # รูปทั้งหมดของสินค้าแต่ละชิ้น (รูปปกหลัก + แกลเลอรี) ใช้ทำสไลด์รูปหลัก/รูปย่อยใน popup สอบถามสินค้า
        images_map = _load_part_images_map(conn, (p["part_sku"] for p in parts_raw))
        parts = []
        for p in parts_raw:
            all_images = ([p["image_filename"]] if p["image_filename"] else []) + \
                         [g["stored_name"] for g in images_map.get(p["part_sku"], [])]
            parts.append(dict(p, images=all_images))
        by_cat = {}
        for p in parts:
            by_cat.setdefault(p["category"], []).append(p)
        parts_by_category = [
            {"category": cat, "label": PRODUCT_CATEGORY_LABELS[cat], "parts": by_cat[cat]}
            for cat in PRODUCT_CATEGORIES if cat in by_cat
        ]
        overview[cid] = {
            "managers": managers,
            "sales_people": sales_people,
            "technicians": technicians,
            "queue": queue,
            "parts": parts,
            "parts_by_category": parts_by_category,
        }

    return {"centers": centers, "centers_with_geo": centers_with_geo, "overview": overview,
            "centers_contact_for_js": centers_contact_for_js, "category_icons": PRODUCT_CATEGORY_ICONS}


def render_login(error):
    """render login.html พร้อมสถานะปุ่ม Google/LINE (ใช้ร่วมกันทุกจุดที่คืนหน้า login พร้อม error) —
    ฟังก์ชัน _provider_configured ประกาศอยู่ถัดจากนี้ในไฟล์ แต่เรียกใช้ได้ปกติเพราะ Python
    ค้นหาชื่อฟังก์ชันตอนเรียกจริง (runtime) ไม่ใช่ตอนประกาศ def"""
    return render("login.html", error=error,
                   google_ready=_provider_configured("google"), line_ready=_provider_configured("line"))


@route("GET", r"/login")
def login_form(environ, m, conn, user):
    if user:
        raise Redirect(ROLE_HOME[user["role"]])
    return render_login(None)


@route("POST", r"/login")
def login_submit(environ, m, conn, user):
    form = parse_post(environ)
    username = form.get("username", "").strip()
    password = form.get("password", "")
    now = time.time()
    attempt_key = (_client_ip(environ), username.lower())

    entry = LOGIN_ATTEMPTS.get(attempt_key)
    if entry and entry.get("locked_until") and now < entry["locked_until"]:
        wait_min = max(1, int((entry["locked_until"] - now) // 60) + 1)
        return render_login(f"พยายามเข้าสู่ระบบผิดหลายครั้งเกินไป กรุณารออีกประมาณ {wait_min} นาทีแล้วลองใหม่")

    row = conn.execute("SELECT * FROM Users WHERE username=?", (username,)).fetchone()
    ok = bool(row) and db.verify_password(password, row["password"])

    if not ok:
        entry = LOGIN_ATTEMPTS.setdefault(attempt_key, {"count": 0, "first_attempt": now, "locked_until": None})
        if now - entry["first_attempt"] > LOGIN_ATTEMPT_WINDOW:
            entry["count"] = 0
            entry["first_attempt"] = now
        entry["count"] += 1
        if entry["count"] >= LOGIN_MAX_ATTEMPTS:
            entry["locked_until"] = now + LOGIN_LOCKOUT_SECONDS
        return render_login("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    LOGIN_ATTEMPTS.pop(attempt_key, None)

    if not row["is_active"]:
        return render_login("บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อแอดมิน")

    # อัปเกรดรหัสผ่านรูปแบบเก่า (SHA-256 ไม่มี salt) เป็นรูปแบบใหม่ทันทีที่ login สำเร็จ
    if not row["password"].startswith("pbkdf2_sha256$"):
        conn.execute("UPDATE Users SET password=? WHERE user_id=?",
                     (db.hash_password(password), row["user_id"]))
        conn.commit()

    token = uuid.uuid4().hex
    SESSIONS[token] = {
        "user_id": row["user_id"],
        "csrf_token": uuid.uuid4().hex,
        "created": now,
        "last_seen": now,
    }
    raise Redirect(ROLE_HOME[row["role"]] + f"::SETCOOKIE::{token}")


@route("GET", r"/logout")
def logout(environ, m, conn, user):
    cookies = parse_cookies(environ)
    SESSIONS.pop(cookies.get("sid"), None)
    raise Redirect("/login::CLEARCOOKIE::")


# --------------------------------------------- สมัครสมาชิกด้วย Google/LINE --
# ลูกค้าใหม่สมัครเข้าใช้งานเองผ่านปุ่ม "สมัครด้วย Google" หรือ "สมัครด้วย LINE" (OAuth2 Authorization
# Code flow มาตรฐาน เขียนด้วย urllib ล้วนๆ ไม่พึ่งไลบรารีภายนอก) จำเป็นต้องตั้งค่า Client ID/Secret
# ของแต่ละผู้ให้บริการเองผ่าน environment variables (ดู db.py) มิฉะนั้นปุ่มจะขึ้นสถานะ "ยังไม่พร้อมใช้งาน"
# หลังยืนยันตัวตนสำเร็จ ถ้ายังไม่เคยสมัครมาก่อนจะพาไปกรอกชื่อ+เบอร์มือถือ (บังคับ) ที่ /signup/complete
# ก่อนสร้างบัญชีลูกค้าจริง แล้วพาไปหน้าเพิ่มเครื่องพิมพ์ของตัวเอง (โควตาเริ่มต้น 3 เครื่อง แอดมินปรับเพิ่มได้)

OAUTH_STATES = {}          # state token -> {"provider", "created"} — กัน CSRF ระหว่างไป-กลับผู้ให้บริการ OAuth
OAUTH_STATE_TTL = 10 * 60  # state ใช้ได้ 10 นาที

PENDING_SIGNUPS = {}           # signup token -> {"provider","sub","name","email","created"} — พักโปรไฟล์รอกรอกเบอร์มือถือ
PENDING_SIGNUP_TTL = 20 * 60   # ลิงก์กรอกข้อมูลต่อใช้ได้ 20 นาที


def _cleanup_expired(store, ttl):
    now = time.time()
    for key in [k for k, v in store.items() if now - v["created"] > ttl]:
        store.pop(key, None)


def _provider_configured(provider):
    if not db.PUBLIC_BASE_URL:
        return False
    if provider == "google":
        return bool(db.GOOGLE_CLIENT_ID and db.GOOGLE_CLIENT_SECRET)
    if provider == "line":
        return bool(db.LINE_CHANNEL_ID and db.LINE_CHANNEL_SECRET)
    return False


def _oauth_redirect_uri(provider):
    return f"{db.PUBLIC_BASE_URL}/auth/{provider}/callback"


def _oauth_http_post_form(url, data):
    """POST แบบ x-www-form-urlencoded ไปยัง token endpoint ของผู้ให้บริการ OAuth แล้วคืนค่า JSON
    คืน (result_dict, None) เมื่อสำเร็จ หรือ (None, error_message) เมื่อล้มเหลว — ไม่โยน exception ออกไป"""
    body = urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        return None, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return None, str(e)


def _oauth_http_get_json(url, bearer_token):
    """GET แบบแนบ Authorization: Bearer <token> แล้วคืนค่า JSON ที่ parse แล้ว — ใช้ดึงโปรไฟล์ผู้ใช้
    จาก userinfo/profile endpoint (แทนการถอดรหัส/ตรวจลายเซ็น ID token JWT เอง เพื่อไม่ต้องพึ่งไลบรารี JWT ภายนอก)"""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer_token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        return None, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return None, str(e)


def _login_user_row(row):
    """สร้าง session ให้ผู้ใช้แถวนี้แล้วคืน Redirect ไปหน้าแรกของบทบาทนั้น (ใช้ร่วมกันทั้งล็อกอิน OAuth ปกติ
    และตอนสมัครสมาชิกใหม่เสร็จ)"""
    token = uuid.uuid4().hex
    now_ts = time.time()
    SESSIONS[token] = {"user_id": row["user_id"], "csrf_token": uuid.uuid4().hex, "created": now_ts, "last_seen": now_ts}
    return token


def _finish_oauth_login(conn, provider, sub, name, email):
    """หลังยืนยันตัวตนกับ Google/LINE สำเร็จ (ได้ sub/ชื่อ/อีเมลมาแล้ว) — ถ้าเคยสมัครไว้แล้วให้ล็อกอินทันที
    ถ้ายังไม่เคยสมัคร ให้พักข้อมูลโปรไฟล์ไว้ชั่วคราวแล้วพาไปกรอกเบอร์มือถือ (บังคับ) ให้ครบก่อนสร้างบัญชีจริง"""
    row = conn.execute(
        "SELECT * FROM Users WHERE auth_provider=? AND oauth_sub=?", (provider, sub)
    ).fetchone()
    if row:
        if not row["is_active"]:
            raise HttpError(403, "บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อแอดมิน")
        token = _login_user_row(row)
        raise Redirect(ROLE_HOME[row["role"]] + f"::SETCOOKIE::{token}")

    _cleanup_expired(PENDING_SIGNUPS, PENDING_SIGNUP_TTL)
    signup_token = uuid.uuid4().hex
    PENDING_SIGNUPS[signup_token] = {
        "provider": provider, "sub": sub, "name": name, "email": email, "created": time.time(),
    }
    raise Redirect(f"/signup/complete?token={signup_token}")


@route("GET", r"/signup")
def signup_form(environ, m, conn, user):
    if user:
        raise Redirect(ROLE_HOME[user["role"]])
    return render("signup.html", google_ready=_provider_configured("google"), line_ready=_provider_configured("line"))


@route("GET", r"/auth/google/start")
def auth_google_start(environ, m, conn, user):
    if not _provider_configured("google"):
        raise HttpError(400, "ระบบยังไม่ได้ตั้งค่าการสมัคร/ล็อกอินด้วย Google (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/PUBLIC_BASE_URL) กรุณาติดต่อแอดมิน")
    _cleanup_expired(OAUTH_STATES, OAUTH_STATE_TTL)
    state = uuid.uuid4().hex
    OAUTH_STATES[state] = {"provider": "google", "created": time.time()}
    params = {
        "client_id": db.GOOGLE_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    raise Redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@route("GET", r"/auth/google/callback")
def auth_google_callback(environ, m, conn, user):
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    code = qs.get("code", [""])[0]
    state = qs.get("state", [""])[0]
    oauth_err = qs.get("error", [""])[0]
    _cleanup_expired(OAUTH_STATES, OAUTH_STATE_TTL)
    entry = OAUTH_STATES.pop(state, None) if state else None
    if oauth_err:
        raise HttpError(400, f"Google ปฏิเสธการเข้าสู่ระบบ: {html.escape(oauth_err)}")
    if not entry or entry["provider"] != "google" or not code:
        raise HttpError(400, "คำขอเข้าสู่ระบบไม่ถูกต้องหรือหมดอายุ กรุณาลองสมัคร/ล็อกอินใหม่อีกครั้งที่หน้าสมัครสมาชิก")
    if not _provider_configured("google"):
        raise HttpError(400, "ระบบยังไม่ได้ตั้งค่าการสมัคร/ล็อกอินด้วย Google")

    token_result, tok_err = _oauth_http_post_form("https://oauth2.googleapis.com/token", {
        "code": code,
        "client_id": db.GOOGLE_CLIENT_ID,
        "client_secret": db.GOOGLE_CLIENT_SECRET,
        "redirect_uri": _oauth_redirect_uri("google"),
        "grant_type": "authorization_code",
    })
    if tok_err or not token_result or "access_token" not in token_result:
        raise HttpError(400, f"เชื่อมต่อ Google เพื่อยืนยันตัวตนไม่สำเร็จ: {html.escape(tok_err or 'ไม่พบ access_token')}")

    profile, prof_err = _oauth_http_get_json(
        "https://openidconnect.googleapis.com/v1/userinfo", token_result["access_token"])
    if prof_err or not profile or not profile.get("sub"):
        raise HttpError(400, f"ดึงข้อมูลโปรไฟล์จาก Google ไม่สำเร็จ: {html.escape(prof_err or '')}")

    return _finish_oauth_login(conn, "google", profile["sub"], profile.get("name") or "", profile.get("email") or "")


@route("GET", r"/auth/line/start")
def auth_line_start(environ, m, conn, user):
    if not _provider_configured("line"):
        raise HttpError(400, "ระบบยังไม่ได้ตั้งค่าการสมัคร/ล็อกอินด้วย LINE (LINE_CHANNEL_ID/LINE_CHANNEL_SECRET/PUBLIC_BASE_URL) กรุณาติดต่อแอดมิน")
    _cleanup_expired(OAUTH_STATES, OAUTH_STATE_TTL)
    state = uuid.uuid4().hex
    OAUTH_STATES[state] = {"provider": "line", "created": time.time()}
    params = {
        "response_type": "code",
        "client_id": db.LINE_CHANNEL_ID,
        "redirect_uri": _oauth_redirect_uri("line"),
        "state": state,
        "scope": "profile openid",
    }
    raise Redirect("https://access.line.me/oauth2/v2.1/authorize?" + urlencode(params))


@route("GET", r"/auth/line/callback")
def auth_line_callback(environ, m, conn, user):
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    code = qs.get("code", [""])[0]
    state = qs.get("state", [""])[0]
    oauth_err = qs.get("error", [""])[0]
    _cleanup_expired(OAUTH_STATES, OAUTH_STATE_TTL)
    entry = OAUTH_STATES.pop(state, None) if state else None
    if oauth_err:
        raise HttpError(400, f"LINE ปฏิเสธการเข้าสู่ระบบ: {html.escape(oauth_err)}")
    if not entry or entry["provider"] != "line" or not code:
        raise HttpError(400, "คำขอเข้าสู่ระบบไม่ถูกต้องหรือหมดอายุ กรุณาลองสมัคร/ล็อกอินใหม่อีกครั้งที่หน้าสมัครสมาชิก")
    if not _provider_configured("line"):
        raise HttpError(400, "ระบบยังไม่ได้ตั้งค่าการสมัคร/ล็อกอินด้วย LINE")

    token_result, tok_err = _oauth_http_post_form("https://api.line.me/oauth2/v2.1/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _oauth_redirect_uri("line"),
        "client_id": db.LINE_CHANNEL_ID,
        "client_secret": db.LINE_CHANNEL_SECRET,
    })
    if tok_err or not token_result or "access_token" not in token_result:
        raise HttpError(400, f"เชื่อมต่อ LINE เพื่อยืนยันตัวตนไม่สำเร็จ: {html.escape(tok_err or 'ไม่พบ access_token')}")

    profile, prof_err = _oauth_http_get_json("https://api.line.me/v2/profile", token_result["access_token"])
    if prof_err or not profile or not profile.get("userId"):
        raise HttpError(400, f"ดึงข้อมูลโปรไฟล์จาก LINE ไม่สำเร็จ: {html.escape(prof_err or '')}")

    return _finish_oauth_login(conn, "line", profile["userId"], profile.get("displayName") or "", "")


PHONE_RE = re.compile(r"^[0-9+\-() ]{9,20}$")


@route("GET", r"/signup/complete")
def signup_complete_form(environ, m, conn, user):
    if user:
        raise Redirect(ROLE_HOME[user["role"]])
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    token = qs.get("token", [""])[0]
    _cleanup_expired(PENDING_SIGNUPS, PENDING_SIGNUP_TTL)
    pending = PENDING_SIGNUPS.get(token)
    if not pending:
        raise HttpError(400, "ลิงก์สมัครสมาชิกนี้หมดอายุหรือไม่ถูกต้อง กรุณาเริ่มสมัครใหม่อีกครั้งที่หน้าสมัครสมาชิก")
    return render("signup_complete.html", token=token, pending=pending, error=None)


@route("POST", r"/signup/complete")
def signup_complete_submit(environ, m, conn, user):
    if user:
        raise Redirect(ROLE_HOME[user["role"]])
    form = parse_post(environ)
    token = form.get("token", "")
    _cleanup_expired(PENDING_SIGNUPS, PENDING_SIGNUP_TTL)
    pending = PENDING_SIGNUPS.get(token)
    if not pending:
        raise HttpError(400, "ลิงก์สมัครสมาชิกนี้หมดอายุหรือไม่ถูกต้อง กรุณาเริ่มสมัครใหม่อีกครั้งที่หน้าสมัครสมาชิก")

    name = form.get("name", "").strip() or pending.get("name") or ""
    phone = form.get("phone", "").strip()
    email = form.get("email", "").strip() or pending.get("email") or ""

    if not name:
        return render("signup_complete.html", token=token, pending=pending, error="กรุณากรอกชื่อ-นามสกุล")
    if not phone or not PHONE_RE.match(phone):
        return render("signup_complete.html", token=token, pending=pending,
                       error="กรุณากรอกเบอร์มือถือให้ถูกต้อง (จำเป็นต้องกรอก)")

    provider, sub = pending["provider"], pending["sub"]
    # กันสร้างบัญชีซ้ำ (เช่นเปิดลิงก์เดิมค้างไว้สองแท็บแล้วกดส่งฟอร์มซ้ำ) — ถ้ามีบัญชีนี้แล้วให้ล็อกอินแทน
    existing = conn.execute(
        "SELECT * FROM Users WHERE auth_provider=? AND oauth_sub=?", (provider, sub)
    ).fetchone()
    if existing:
        PENDING_SIGNUPS.pop(token, None)
        tok = _login_user_row(existing)
        raise Redirect(ROLE_HOME[existing["role"]] + f"::SETCOOKIE::{tok}")

    cur = conn.execute(
        "INSERT INTO Customers (name, phone, email, device_quota) VALUES (?,?,?,?)",
        (name, phone, email, db.DEFAULT_DEVICE_QUOTA),
    )
    customer_id = cur.lastrowid
    username = f"{provider}_{sub}"[:64]
    conn.execute(
        "INSERT INTO Users (username, password, role, name, phone, customer_id, is_active, auth_provider, oauth_sub, created_at) "
        "VALUES (?,?,?,?,?,?,1,?,?,?)",
        (username, db.hash_password(uuid.uuid4().hex), "customer", name, phone, customer_id, provider, sub, db.now()),
    )
    user_row = conn.execute("SELECT * FROM Users WHERE username=?", (username,)).fetchone()
    conn.commit()
    _sync_customer_to_odoo(conn, customer_id)
    PENDING_SIGNUPS.pop(token, None)

    tok = _login_user_row(user_row)
    raise Redirect(f"/customer/devices/new?welcome=1::SETCOOKIE::{tok}")


# ---------------------------------------------------------- user guide ----
# คู่มือใช้งาน แยกตามส่วนงาน — เข้าถึงได้เฉพาะ role ที่เกี่ยวข้อง (admin เห็นได้ทุกส่วน)
# roles=None หมายถึงหน้า public เปิดดูได้โดยไม่ต้อง login

GUIDE_SECTIONS = [
    {"slug": "public", "title": "หน้าเว็บสาธารณะ", "icon": "🌐",
     "subtitle": "หน้าแรก ดูสินค้า และเช็กสถานะงานซ่อม (ไม่ต้อง login)", "roles": None},
    {"slug": "admin", "title": "แอดมิน", "icon": "🛠️",
     "subtitle": "จัดการระบบทั้งหมด ผู้ใช้งาน ศูนย์บริการ รายงาน", "roles": {"admin"}},
    {"slug": "manager_sales", "title": "ผู้จัดการศูนย์ / เซล", "icon": "🏢",
     "subtitle": "จัดการงานซ่อมและการขายภายในศูนย์", "roles": {"admin", "manager", "sales"}},
    {"slug": "technician", "title": "ช่างซ่อม", "icon": "🔧",
     "subtitle": "รับงาน บันทึกการซ่อม เบิกอะไหล่ ออกใบเสนอราคา/ใบแจ้งหนี้", "roles": {"admin", "technician"}},
    {"slug": "customer", "title": "ลูกค้า", "icon": "🧑‍💻",
     "subtitle": "แจ้งซ่อม ติดตามสถานะ ดูใบเสนอราคา/ใบแจ้งหนี้", "roles": {"admin", "customer"}},
]
GUIDE_SECTIONS_BY_SLUG = {s["slug"]: s for s in GUIDE_SECTIONS}


def guide_allowed(user, section):
    """ตรวจสิทธิ์เข้าถึงคู่มือส่วนงานหนึ่งๆ — public (roles=None) เปิดให้ทุกคนเสมอ,
    admin เข้าได้ทุกส่วน, role อื่นเข้าได้เฉพาะส่วนของตัวเอง"""
    if section["roles"] is None:
        return True
    if user is None:
        return False
    return user["role"] == "admin" or user["role"] in section["roles"]


@route("GET", r"/guide")
def guide_index(environ, m, conn, user):
    sections = [dict(s, allowed=guide_allowed(user, s)) for s in GUIDE_SECTIONS]
    return render("guide_index.html", sections=sections, user=user)


@route("GET", r"/guide/([a-z_]+)")
def guide_detail(environ, m, conn, user):
    slug = m.group(1)
    section = GUIDE_SECTIONS_BY_SLUG.get(slug)
    if section is None:
        raise HttpError(404, "ไม่พบคู่มือส่วนนี้")
    if not guide_allowed(user, section):
        if user is None and section["roles"] is not None:
            raise Redirect("/login")
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงคู่มือส่วนนี้")
    return render(f"guide_{slug}.html", section=section, user=user)


# ------------------------------------------------------- public tracking --

@route("GET", r"/track")
def track(environ, m, conn, user):
    qs = parse_qs(urlparse(environ.get("QUERY_STRING", "")).query if False else environ.get("QUERY_STRING", ""))
    sn = qs.get("sn", [""])[0].strip()
    device = None
    tickets = []
    if sn:
        device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
        if device:
            tickets = conn.execute(
                "SELECT * FROM Tickets WHERE device_sn=? ORDER BY created_at DESC", (sn,)
            ).fetchall()
    return render("track.html", sn=sn, device=device, tickets=tickets, user=user,
                   status_index={s: i for i, s in enumerate(db.STATUSES)})


# ------------------------------------------------------------ customer ---

@route("GET", r"/customer/dashboard")
def customer_dashboard(environ, m, conn, user):
    """Dashboard สรุปภาพรวมสำหรับลูกค้า — จำนวนตั๋วซ่อมของตัวเองแยกตามสถานะ + สถานะเครื่องพิมพ์/บำรุงรักษา
    คลิกตัวเลขบนการ์ดเพื่อดู popup รายการรายละเอียดได้ทุกช่อง (รูปแบบเดียวกับ Dashboard ฝั่งแอดมิน)"""
    require_login(user, "customer")
    _sync_maintenance_notifications(conn)

    device_type_labels = {"FDM": "FDM", "Resin": "Resin", "Wash & Cure": "Wash & Cure", "Other": "อื่นๆ"}

    # --- ตั๋วซ่อมของฉัน แยกตามสถานะ ---
    ticket_rows = conn.execute(
        """SELECT t.ticket_id, t.status, t.created_at, d.model FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           WHERE d.customer_id = ?
           ORDER BY t.created_at DESC""",
        (user["customer_id"],),
    ).fetchall()
    counts = Counter(r["status"] for r in ticket_rows)
    total = len(ticket_rows)
    customer_cases_for_js = {s: [] for s in db.STATUSES}
    customer_cases_for_js["total"] = []
    for r in ticket_rows:
        item = {
            "ticket_id": r["ticket_id"], "model": r["model"], "status": r["status"],
            "status_label": db.STATUS_LABELS.get(r["status"], r["status"]), "date": r["created_at"],
        }
        customer_cases_for_js["total"].append(item)
        if r["status"] in customer_cases_for_js:
            customer_cases_for_js[r["status"]].append(item)

    # --- เครื่องพิมพ์ / บำรุงรักษา (เฉพาะเครื่องที่ยังใช้งานอยู่) ---
    devices = conn.execute(
        "SELECT * FROM Devices WHERE customer_id=? AND status='Active' ORDER BY model", (user["customer_id"],)
    ).fetchall()
    device_rows = []
    for d in devices:
        overview = _device_overview_status(conn, d)
        device_rows.append(dict(d, overview=overview))
    summary = Counter(r["overview"]["status"] for r in device_rows)

    customer_devices_for_js = {"ready": [], "maintenance_due": [], "in_repair": [], "decommissioned": [], "sold": []}
    for r in device_rows:
        item = {
            "device_sn": r["device_sn"], "model": r["model"], "total_usage_hours": r["total_usage_hours"],
            "open_ticket_id": r["overview"]["open_ticket_id"],
            "due_tasks": [f"{t['task_name']} — {t['overdue_label'] or ''}" for t in r["overview"]["due_tasks"]],
        }
        bucket = r["overview"]["status"]
        if bucket in customer_devices_for_js:
            customer_devices_for_js[bucket].append(item)

    # --- เครื่องที่เลิกใช้แล้ว/ขายต่อแล้ว — แสดงแยกเป็นการ์ดเพิ่มเติม ไม่รวมกับสถานะพร้อมใช้งาน/บำรุงรักษาด้านบน
    # (เครื่องกลุ่มนี้เลิกใช้งานจริงแล้ว จึงไม่คำนวณรอบบำรุงรักษา/ตั๋วซ่อมค้างให้)
    inactive_devices = conn.execute(
        "SELECT * FROM Devices WHERE customer_id=? AND status IN ('Decommissioned','Sold') ORDER BY model",
        (user["customer_id"],),
    ).fetchall()
    for d in inactive_devices:
        bucket = "decommissioned" if d["status"] == "Decommissioned" else "sold"
        summary[bucket] += 1
        customer_devices_for_js[bucket].append({
            "device_sn": d["device_sn"], "model": d["model"], "total_usage_hours": d["total_usage_hours"],
            "open_ticket_id": None, "due_tasks": [],
        })

    # --- แยกจำนวนเครื่องตามประเภท (FDM / Resin / Wash & Cure / Other) — แสดงบนสุดของ Dashboard ---
    OVERVIEW_STATUS_LABELS = {"ready": "✅ พร้อมใช้งาน", "maintenance_due": "🛠️ ถึงรอบบำรุงรักษา", "in_repair": "🔩 กำลังซ่อม"}
    type_counts = Counter(r["type"] for r in device_rows)
    customer_devices_by_type_for_js = {t: [] for t in db.DEVICE_TYPES}
    for r in device_rows:
        item = {
            "device_sn": r["device_sn"], "model": r["model"], "total_usage_hours": r["total_usage_hours"],
            "status": r["overview"]["status"], "status_label": OVERVIEW_STATUS_LABELS.get(r["overview"]["status"], r["overview"]["status"]),
        }
        if r["type"] in customer_devices_by_type_for_js:
            customer_devices_by_type_for_js[r["type"]].append(item)

    # --- แผนที่ตำแหน่งของฉัน + ศูนย์บริการทั้งหมด — ตำแหน่งลูกค้ามาจาก Geolocation API ของเบราว์เซอร์
    # (บันทึกอัตโนมัติตอนเข้าหน้า "เพิ่มเครื่องพิมพ์ของฉัน" ถ้าอนุญาต) หรือแอดมินกรอกให้เองก็ได้ที่หน้าลูกค้า/เครื่อง
    my_customer_row = conn.execute(
        "SELECT name, latitude, longitude FROM Customers WHERE customer_id=?", (user["customer_id"],)
    ).fetchone()
    my_location = None
    if my_customer_row and my_customer_row["latitude"] is not None and my_customer_row["longitude"] is not None:
        my_location = {
            "name": my_customer_row["name"],
            "latitude": my_customer_row["latitude"],
            "longitude": my_customer_row["longitude"],
        }
    centers_with_geo = [
        c for c in annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall())
        if c["latitude"] is not None and c["longitude"] is not None
    ]

    return render(
        "customer_dashboard.html", user=user, counts=counts, total=total,
        customer_cases_for_js=customer_cases_for_js, summary=summary,
        customer_devices_for_js=customer_devices_for_js,
        device_type_labels=device_type_labels, type_counts=type_counts,
        customer_devices_by_type_for_js=customer_devices_by_type_for_js,
        my_location=my_location, centers_with_geo=centers_with_geo,
    )


@route("GET", r"/customer/tickets")
def customer_tickets(environ, m, conn, user):
    require_login(user, "customer")
    rows = conn.execute(
        """SELECT t.*, d.model, sc.name AS center_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE d.customer_id = ?
           ORDER BY t.created_at DESC""",
        (user["customer_id"],),
    ).fetchall()
    return render("customer_tickets.html", tickets=rows, user=user)


@route("GET", r"/customer/devices/new")
def customer_device_new_form(environ, m, conn, user):
    """หน้าลงทะเบียนเครื่องพิมพ์ของตัวเอง (self-service) — ใช้ทั้งตอนสมัครสมาชิกใหม่ (มาจาก
    /signup/complete) และภายหลังเมื่อลูกค้าอยากเพิ่มเครื่องเองในบัญชี จำกัดจำนวนตามโควตา
    Customers.device_quota (ค่าเริ่มต้น 3 เครื่อง แอดมินปรับเพิ่มได้ที่หน้าลูกค้า/เครื่อง)"""
    require_login(user, "customer")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    welcome = qs.get("welcome", ["0"])[0] == "1"
    just_added = qs.get("added", ["0"])[0] == "1"
    customer = conn.execute("SELECT * FROM Customers WHERE customer_id=?", (user["customer_id"],)).fetchone()
    device_count = conn.execute(
        "SELECT COUNT(*) AS c FROM Devices WHERE customer_id=?", (user["customer_id"],)
    ).fetchone()["c"]
    quota = customer["device_quota"] if customer else db.DEFAULT_DEVICE_QUOTA
    my_devices = conn.execute(
        "SELECT * FROM Devices WHERE customer_id=? ORDER BY created_at DESC", (user["customer_id"],)
    ).fetchall()
    return render(
        "customer_device_new.html", user=user, welcome=welcome, just_added=just_added, device_count=device_count,
        quota=quota, quota_reached=device_count >= quota, my_devices=my_devices, error=None,
        device_status_labels=DEVICE_STATUS_LABELS, max_device_proof_mb=MAX_DEVICE_PROOF_MB,
    )


@route("POST", r"/customer/devices/new")
def customer_device_new_submit(environ, m, conn, user):
    require_login(user, "customer")
    form, files = parse_multipart(environ)
    customer = conn.execute("SELECT * FROM Customers WHERE customer_id=?", (user["customer_id"],)).fetchone()
    quota = customer["device_quota"] if customer else db.DEFAULT_DEVICE_QUOTA
    device_count = conn.execute(
        "SELECT COUNT(*) AS c FROM Devices WHERE customer_id=?", (user["customer_id"],)
    ).fetchone()["c"]

    def _reject(error_msg):
        my_devices = conn.execute(
            "SELECT * FROM Devices WHERE customer_id=? ORDER BY created_at DESC", (user["customer_id"],)
        ).fetchall()
        return render(
            "customer_device_new.html", user=user, welcome=False, just_added=False, device_count=device_count,
            quota=quota, quota_reached=device_count >= quota, my_devices=my_devices, error=error_msg,
            device_status_labels=DEVICE_STATUS_LABELS, max_device_proof_mb=MAX_DEVICE_PROOF_MB,
        )

    if device_count >= quota:
        return _reject(f"คุณลงทะเบียนเครื่องพิมพ์ครบโควตาแล้ว ({quota} เครื่อง) กรุณาติดต่อแอดมินหากต้องการเพิ่มโควตา")

    sn = form.get("device_sn", "").strip()
    model = form.get("model", "").strip()
    device_type = form.get("type") if form.get("type") in db.DEVICE_TYPES else "FDM"
    if not sn or not model:
        return _reject("กรุณากรอกหมายเลขเครื่อง (SN) และรุ่นเครื่องพิมพ์ให้ครบ")

    dup = conn.execute("SELECT 1 FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if dup:
        return _reject(f"หมายเลขเครื่อง (SN) '{sn}' มีอยู่ในระบบแล้ว กรุณาตรวจสอบอีกครั้งหรือติดต่อแอดมิน")

    purchase_d = _parse_date_or_none(form.get("purchase_date"))
    warranty_d = _parse_date_or_none(form.get("warranty_end_date"))
    if purchase_d and warranty_d:
        if warranty_d < purchase_d:
            return _reject("วันหมดประกันต้องไม่ก่อนวันที่ซื้อ")
        max_warranty = _add_years(purchase_d, 3)
        if warranty_d > max_warranty:
            return _reject(f"วันหมดประกันต้องไม่เกิน 3 ปีนับจากวันที่ซื้อ (ไม่เกินวันที่ {max_warranty.strftime('%Y-%m-%d')})")

    proof_file = (files.get("purchase_proof") or [None])[0]
    try:
        proof_stored = save_device_proof(sn, proof_file)
    except ValueError as e:
        return _reject(str(e))

    conn.execute(
        """INSERT INTO Devices (device_sn, customer_id, model, type, purchase_date, warranty_end_date, status,
           created_at, purchase_proof_filename) VALUES (?,?,?,?,?,?,'Active',?,?)""",
        (sn, user["customer_id"], model, device_type,
         form.get("purchase_date") or None, form.get("warranty_end_date") or None, db.now(), proof_stored),
    )
    conn.commit()
    raise Redirect("/customer/devices/new?added=1")


@route("POST", r"/customer/location/update")
def customer_location_update(environ, m, conn, user):
    """รับพิกัด (ละติจูด/ลองจิจูด) จาก Geolocation API ของเบราว์เซอร์ลูกค้าแบบเงียบๆ (เรียกด้วย fetch()
    จากหน้า "เครื่องพิมพ์ของฉัน" โดยอัตโนมัติ ไม่ต้องกดปุ่มอะไร) — ใช้แสดงตำแหน่งลูกค้าบนแผนที่ Dashboard
    ไม่ใช่หน้าเว็บปกติ จึงคืนแค่ข้อความสั้นๆ พอ (ฝั่ง JS ไม่ได้อ่านเนื้อหา response ใดๆ ต่อ)"""
    require_login(user, "customer")
    form = parse_post(environ)
    try:
        lat = float(form.get("latitude", ""))
        lng = float(form.get("longitude", ""))
    except (TypeError, ValueError):
        return b"invalid"
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return b"invalid"
    conn.execute(
        "UPDATE Customers SET latitude=?, longitude=? WHERE customer_id=?",
        (lat, lng, user["customer_id"]),
    )
    conn.commit()
    return b"ok"


@route("GET", r"/customer/maintenance")
def customer_maintenance_dashboard(environ, m, conn, user):
    """Dashboard บำรุงรักษาเครื่องพิมพ์ของลูกค้า — แสดงสถานะเครื่องทั้งหมดที่ตัวเองเป็นเจ้าของ
    (พร้อมใช้งาน / ถึงรอบบำรุงรักษา / กำลังซ่อม) พร้อมรายการงานบำรุงรักษาที่ครบกำหนดของแต่ละเครื่อง"""
    require_login(user, "customer")
    _sync_maintenance_notifications(conn)
    devices = conn.execute(
        "SELECT * FROM Devices WHERE customer_id=? AND status='Active' ORDER BY model", (user["customer_id"],)
    ).fetchall()
    device_rows = []
    for d in devices:
        overview = _device_overview_status(conn, d)
        device_rows.append(dict(d, overview=overview))
    summary = Counter(r["overview"]["status"] for r in device_rows)
    return render("customer_maintenance.html", devices=device_rows, user=user,
                   summary=summary, device_type_labels={"FDM": "FDM", "Resin": "Resin",
                                                          "Wash & Cure": "Wash & Cure", "Other": "อื่นๆ"})


MAX_RECENT_CENTERS = 3


def _recent_centers_for_customer(conn, customer_id, repair_centers):
    """คืนศูนย์บริการสูงสุด MAX_RECENT_CENTERS แห่งที่ลูกค้าคนนี้เคยเลือกเข้ารับบริการล่าสุด
    (อิงจากตั๋วซ่อมเก่าของลูกค้าคนนี้เอง เรียงจากล่าสุดไปเก่าสุด) เพื่อไม่ต้องแสดงทุกศูนย์บริการ
    ให้เลือกจนล้นตา — ถ้าลูกค้าไม่เคยแจ้งซ่อมมาก่อนเลย จะ fallback ไปใช้ 3 ศูนย์แรกในระบบแทน
    คืนค่า (recent_centers, preferred_center_id) — preferred_center_id ใช้เลือกศูนย์ล่าสุดไว้ให้อัตโนมัติ"""
    rows = conn.execute(
        """SELECT t.center_id, MAX(t.created_at) AS last_used
           FROM Tickets t JOIN Devices d ON d.device_sn = t.device_sn
           WHERE d.customer_id=? AND t.center_id IS NOT NULL
           GROUP BY t.center_id
           ORDER BY last_used DESC
           LIMIT ?""",
        (customer_id, MAX_RECENT_CENTERS),
    ).fetchall()
    centers_by_id = {c["center_id"]: c for c in repair_centers}
    recent = [centers_by_id[r["center_id"]] for r in rows if r["center_id"] in centers_by_id]
    if recent:
        return recent, recent[0]["center_id"]
    fallback = repair_centers[:MAX_RECENT_CENTERS]
    return fallback, (fallback[0]["center_id"] if fallback else None)


def _open_ticket_device_sns(conn):
    """SN ของเครื่องพิมพ์ทุกเครื่องที่มีตั๋วซ่อมค้างอยู่ (ยังไม่ Resolved/Closed) — ใช้กันไม่ให้
    ลูกค้าแจ้งซ่อมซ้ำเครื่องเดิมจนกว่าตั๋วเก่าจะปิดงานก่อน (เครื่องอื่นของลูกค้าคนเดียวกันยังแจ้งซ่อมได้ปกติ)"""
    return {r["device_sn"] for r in conn.execute(
        "SELECT DISTINCT device_sn FROM Tickets WHERE status != 'Resolved/Closed'"
    ).fetchall()}


def _parse_booking_fields(fields):
    """แยกและตรวจสอบข้อมูลการจองคิว (วันนัด + ช่วงเวลา) จากฟอร์มแจ้งซ่อม — ใช้ร่วมกันทั้งหน้าลูกค้าแจ้งซ่อม
    เองและหน้าเจ้าหน้าที่แจ้งซ่อมแทนลูกค้า คืนค่า (channel, booking_date, booking_time_slot, error)
    ticket_mode='booking' ในฟอร์ม = ลูกค้า/เจ้าหน้าที่ต้องการนัดวันเข้ารับบริการ (ไม่ใช่แจ้งซ่อมทันที)"""
    if fields.get("ticket_mode") != "booking":
        return "online_report", None, None, None
    booking_date = fields.get("booking_date", "").strip()
    booking_time_slot = fields.get("booking_time_slot", "").strip()
    if not booking_date or not booking_time_slot:
        return None, None, None, "กรุณาเลือกวันที่และช่วงเวลาที่ต้องการนัดหมาย"
    if booking_time_slot not in BOOKING_TIME_SLOTS:
        return None, None, None, "ช่วงเวลานัดหมายไม่ถูกต้อง"
    try:
        booking_dt = datetime.datetime.strptime(booking_date, "%Y-%m-%d").date()
    except ValueError:
        return None, None, None, "รูปแบบวันที่นัดหมายไม่ถูกต้อง"
    if booking_dt < datetime.date.today():
        return None, None, None, "วันที่นัดหมายต้องไม่ใช่วันที่ผ่านมาแล้ว"
    return "booking", booking_date, booking_time_slot, None


def _log_status_history(conn, ticket_id, from_status, to_status, changed_by, note=None):
    """บันทึกประวัติการเปลี่ยนสถานะ/มอบหมายช่างของตั๋วซ่อม — เรียกทุกครั้งที่สร้างตั๋วใหม่ (from_status=None)
    หรือเปลี่ยนสถานะ/มอบหมายช่างใหม่ (จากหน้าคัมบัง/หน้าช่าง) ใช้แสดงเป็นไทม์ไลน์บนหน้ารายละเอียดตั๋ว"""
    conn.execute(
        "INSERT INTO Ticket_Status_History (ticket_id, from_status, to_status, changed_by, note, changed_at) "
        "VALUES (?,?,?,?,?,?)",
        (ticket_id, from_status, to_status, changed_by, note, db.now()),
    )


def _ticket_status_history(conn, ticket_id):
    """ประวัติการเปลี่ยนสถานะของตั๋วซ่อมใบหนึ่ง เรียงเก่า→ใหม่ พร้อมชื่อผู้ทำรายการ — ใช้แสดงเป็นไทม์ไลน์
    บนหน้ารายละเอียดตั๋ว (ทั้งฝั่งลูกค้า/แอดมิน-ผู้จัดการ/ช่าง)"""
    rows = conn.execute(
        """SELECT h.*, u.name AS changed_by_name FROM Ticket_Status_History h
           LEFT JOIN Users u ON u.user_id = h.changed_by
           WHERE h.ticket_id=? ORDER BY h.history_id""",
        (ticket_id,),
    ).fetchall()
    return [dict(r, from_label=(db.STATUS_LABELS.get(r["from_status"], r["from_status"]) if r["from_status"] else None),
                 to_label=db.STATUS_LABELS.get(r["to_status"], r["to_status"]))
            for r in rows]


@route("GET", r"/customer/new")
def customer_new_form(environ, m, conn, user):
    require_login(user, "customer")
    devices_raw = conn.execute(
        "SELECT * FROM Devices WHERE customer_id=? AND status='Active'", (user["customer_id"],)
    ).fetchall()
    open_sns = _open_ticket_device_sns(conn)
    devices = [dict(d, has_open_ticket=(d["device_sn"] in open_sns)) for d in devices_raw]
    centers_all = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
    repair_centers = [c for c in centers_all if c["supports_fdm"] or c["supports_resin"]]
    centers, preferred_center_id = _recent_centers_for_customer(conn, user["customer_id"], repair_centers)
    centers_with_geo = [c for c in repair_centers if c["latitude"] is not None and c["longitude"] is not None]
    return render("customer_new_ticket.html", devices=devices, user=user, error=None,
                   centers=centers, all_centers=repair_centers, centers_with_geo=centers_with_geo,
                   preferred_center_id=preferred_center_id,
                   max_images=MAX_IMAGES, max_video_mb=MAX_VIDEO_MB, booking_time_slots=BOOKING_TIME_SLOTS)


@route("POST", r"/customer/new")
def customer_new_submit(environ, m, conn, user):
    require_login(user, "customer")
    fields, files = parse_multipart(environ)
    device_sn = fields.get("device_sn", "")

    def with_error(msg):
        devices_raw = conn.execute(
            "SELECT * FROM Devices WHERE customer_id=? AND status='Active'", (user["customer_id"],)
        ).fetchall()
        open_sns = _open_ticket_device_sns(conn)
        devices = [dict(d, has_open_ticket=(d["device_sn"] in open_sns)) for d in devices_raw]
        centers_all = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
        repair_centers = [c for c in centers_all if c["supports_fdm"] or c["supports_resin"]]
        centers, preferred_center_id = _recent_centers_for_customer(conn, user["customer_id"], repair_centers)
        centers_with_geo = [c for c in repair_centers if c["latitude"] is not None and c["longitude"] is not None]
        return render("customer_new_ticket.html", devices=devices, user=user, error=msg,
                       centers=centers, all_centers=repair_centers, centers_with_geo=centers_with_geo,
                       preferred_center_id=preferred_center_id,
                       max_images=MAX_IMAGES, max_video_mb=MAX_VIDEO_MB, booking_time_slots=BOOKING_TIME_SLOTS)

    owned = conn.execute(
        "SELECT 1 FROM Devices WHERE device_sn=? AND customer_id=? AND status='Active'",
        (device_sn, user["customer_id"]),
    ).fetchone()
    if not owned:
        return with_error("ไม่พบเครื่องพิมพ์นี้ในบัญชีของคุณ")

    open_ticket = conn.execute(
        "SELECT ticket_id FROM Tickets WHERE device_sn=? AND status != 'Resolved/Closed'", (device_sn,)
    ).fetchone()
    if open_ticket:
        return with_error(
            f"เครื่องนี้มีตั๋วซ่อม #{open_ticket['ticket_id']} ที่ยังไม่เสร็จอยู่แล้ว "
            "กรุณารอให้ซ่อมเสร็จก่อน จึงจะแจ้งซ่อมเครื่องนี้ใหม่ได้"
        )

    any_centers = conn.execute(
        "SELECT COUNT(*) c FROM Service_Centers WHERE supports_fdm=1 OR supports_resin=1"
    ).fetchone()["c"]
    center_id = fields.get("center_id") or None
    if any_centers and not center_id:
        return with_error("กรุณาเลือกสาขาที่ต้องการเข้ารับบริการ")
    if center_id:
        center_ok = conn.execute(
            "SELECT 1 FROM Service_Centers WHERE center_id=? AND (supports_fdm=1 OR supports_resin=1)",
            (center_id,),
        ).fetchone()
        if not center_ok:
            return with_error("สาขาที่เลือกไม่รับซ่อม กรุณาเลือกสาขาอื่น")

    channel, booking_date, booking_time_slot, booking_err = _parse_booking_fields(fields)
    if booking_err:
        return with_error(booking_err)

    images = files.get("images", [])
    videos = files.get("video", [])

    if len(images) > MAX_IMAGES:
        return with_error(f"อัปโหลดรูปภาพได้สูงสุด {MAX_IMAGES} รูป (เลือกมา {len(images)} รูป)")
    for f in images:
        if not f["content_type"].startswith("image/"):
            return with_error(f"ไฟล์ '{f['filename']}' ไม่ใช่ไฟล์รูปภาพที่รองรับ")

    if len(videos) > 1:
        return with_error("อัปโหลดวิดีโอได้สูงสุด 1 คลิป")
    video = videos[0] if videos else None
    if video:
        if not video["content_type"].startswith("video/"):
            return with_error(f"ไฟล์ '{video['filename']}' ไม่ใช่ไฟล์วิดีโอที่รองรับ")
        if len(video["data"]) > MAX_VIDEO_BYTES:
            size_mb = round(len(video["data"]) / (1024 * 1024), 1)
            return with_error(f"ไฟล์วิดีโอขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_VIDEO_MB} MB)")

    cur = conn.execute(
        """INSERT INTO Tickets (device_sn, issue_category, description, center_id, status, created_at,
                                 channel, booking_date, booking_time_slot)
           VALUES (?,?,?,?, 'New', ?,?,?,?)""",
        (device_sn, fields.get("issue_category", ""), fields.get("description", ""), center_id, db.now(),
         channel, booking_date, booking_time_slot),
    )
    ticket_id = cur.lastrowid
    note = f"ลูกค้าจองคิวเข้ารับบริการวันที่ {booking_date} ช่วง {booking_time_slot}" if channel == "booking" else None
    _log_status_history(conn, ticket_id, None, "New", user["user_id"], note=note)

    if images or video:
        ticket_dir = os.path.join(UPLOADS_DIR, str(ticket_id))
        os.makedirs(ticket_dir, exist_ok=True)
        for idx, f in enumerate(images, start=1):
            stored = f"img{idx}_{safe_filename(f['filename'])}"
            with open(os.path.join(ticket_dir, stored), "wb") as out:
                out.write(f["data"])
            conn.execute(
                "INSERT INTO Ticket_Media (ticket_id, media_type, filename, stored_name, uploaded_at) VALUES (?,?,?,?,?)",
                (ticket_id, "image", f["filename"], stored, db.now()),
            )
        if video:
            stored = f"video_{safe_filename(video['filename'])}"
            with open(os.path.join(ticket_dir, stored), "wb") as out:
                out.write(video["data"])
            conn.execute(
                "INSERT INTO Ticket_Media (ticket_id, media_type, filename, stored_name, uploaded_at) VALUES (?,?,?,?,?)",
                (ticket_id, "video", video["filename"], stored, db.now()),
            )

    conn.commit()
    raise Redirect("/customer/tickets")


@route("GET", r"/customer/ticket/(\d+)")
def customer_ticket_detail(environ, m, conn, user):
    require_login(user, "customer")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, d.customer_id, sc.name AS center_name, sc.phone AS center_phone,
                  u.name AS tech_name
           FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["customer_id"] != user["customer_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    logs = _service_logs_with_media(conn, ticket_id)
    media = conn.execute(
        "SELECT * FROM Ticket_Media WHERE ticket_id=? AND service_log_id IS NULL ORDER BY media_id", (ticket_id,)
    ).fetchall()
    quotes = get_quotes_for_ticket(conn, ticket_id)
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    payments = get_payments_for_ticket(conn, ticket_id)
    centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
    status_history = _ticket_status_history(conn, ticket_id)
    return render("customer_ticket_detail.html", t=t, logs=logs, media=media, user=user,
                   quotes=quotes, invoice_items=invoice_items, invoice_total=invoice_total, payments=payments,
                   centers=centers, status_index={s: i for i, s in enumerate(db.STATUSES)},
                   status_history=status_history)


@route("POST", r"/customer/ticket/(\d+)/edit")
def customer_ticket_edit(environ, m, conn, user):
    require_login(user, "customer")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.customer_id FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["customer_id"] != user["customer_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    # แก้ไขได้เฉพาะตอนยังไม่มีช่างเริ่มดำเนินการ (สถานะ "รอซ่อม" เท่านั้น) — สถานะอื่นแก้ไม่ได้
    if t["status"] != "New":
        raise HttpError(403, "แก้ไขรายการแจ้งซ่อมได้เฉพาะตอนที่ยังอยู่ในสถานะ 'รอซ่อม' เท่านั้น")

    form = parse_post(environ)
    center_id = form.get("center_id") or None
    if center_id:
        center_ok = conn.execute("SELECT 1 FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
        if not center_ok:
            raise HttpError(400, "สาขาที่เลือกไม่ถูกต้อง")

    conn.execute(
        "UPDATE Tickets SET issue_category=?, description=?, center_id=? WHERE ticket_id=?",
        (form.get("issue_category", ""), form.get("description", ""), center_id, ticket_id),
    )
    conn.commit()
    raise Redirect(f"/customer/ticket/{ticket_id}")


@route("POST", r"/customer/ticket/(\d+)/cancel")
def customer_ticket_cancel(environ, m, conn, user):
    require_login(user, "customer")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.customer_id FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["customer_id"] != user["customer_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    # ยกเลิกได้เฉพาะตอนยังไม่มีช่างเริ่มดำเนินการ (สถานะ "รอซ่อม" เท่านั้น) — สถานะอื่นยกเลิกไม่ได้
    if t["status"] != "New":
        raise HttpError(403, "ยกเลิกรายการแจ้งซ่อมได้เฉพาะตอนที่ยังอยู่ในสถานะ 'รอซ่อม' เท่านั้น")

    media = conn.execute("SELECT * FROM Ticket_Media WHERE ticket_id=?", (ticket_id,)).fetchall()
    for md in media:
        try:
            os.remove(os.path.join(UPLOADS_DIR, str(ticket_id), md["stored_name"]))
        except OSError:
            pass
    conn.execute("DELETE FROM Ticket_Media WHERE ticket_id=?", (ticket_id,))
    conn.execute("DELETE FROM Tickets WHERE ticket_id=?", (ticket_id,))
    conn.commit()
    raise Redirect("/customer/tickets")


@route("POST", r"/customer/ticket/(\d+)/csat")
def customer_csat(environ, m, conn, user):
    require_login(user, "customer")
    ticket_id = int(m.group(1))
    form = parse_post(environ)
    conn.execute(
        "UPDATE Tickets SET csat_score=?, csat_comment=? WHERE ticket_id=?",
        (form.get("score", ""), form.get("comment", ""), ticket_id),
    )
    conn.commit()
    raise Redirect(f"/customer/ticket/{ticket_id}")


# ---------------------------------------------------------------- admin --

# --------------------------------------------------- Maintenance Scheduler --
# คำนวณรอบบำรุงรักษาอัตโนมัติทีละงานตามแผน (Maintenance_Plan_Items) รองรับ 2 แบบ:
#   - interval_type='days'  นับจากวันที่บำรุงรักษาครั้งล่าสุด (เช่น ทุก 7/30 วัน)
#   - interval_type='hours' นับจากชั่วโมงใช้งานสะสมของเครื่อง (Devices.total_usage_hours) เทียบกับ
#                            ชั่วโมงสะสม ณ ตอนบำรุงรักษาครั้งล่าสุด (เช่น ทุก 50/200/500 ชม.)
# ชั่วโมงใช้งานสะสมมาจากการที่ลูกค้า/ช่างกรอกเองตอน "เริ่มงานพิมพ์" แต่ละครั้ง (ไม่มีการเชื่อมต่อฮาร์ดแวร์จริง)

def _maintenance_plan_items_for_type(conn, device_type, active_only=True):
    """แผนบำรุงรักษาที่ตรงกับประเภทเครื่องนี้ — รวมรายการที่ device_type=NULL (ใช้กับทุกประเภท) ด้วยเสมอ"""
    cond = " AND is_active=1" if active_only else ""
    return conn.execute(
        f"SELECT * FROM Maintenance_Plan_Items WHERE (device_type=? OR device_type IS NULL){cond} "
        "ORDER BY device_type IS NULL, interval_type, interval_value",
        (device_type,),
    ).fetchall()


def _device_task_status(conn, device_sn, device_type, total_usage_hours):
    """คำนวณสถานะบำรุงรักษาของเครื่องนี้ทีละงานตามแผน — คืน list ของ dict อธิบายแต่ละงาน พร้อมสถานะ
    ครบกำหนดหรือไม่ (due) และข้อความอธิบาย (overdue_label) เรียงงานที่ครบกำหนดไว้ก่อนเสมอ"""
    plans = _maintenance_plan_items_for_type(conn, device_type)
    today = datetime.date.today()
    results = []
    for p in plans:
        last = conn.execute(
            """SELECT performed_at, hours_at_maintenance FROM Maintenance_Logs
               WHERE device_sn=? AND plan_item_id=?
               ORDER BY performed_at DESC, maintenance_id DESC LIMIT 1""",
            (device_sn, p["plan_item_id"]),
        ).fetchone()
        last_done_at = last["performed_at"][:10] if last and last["performed_at"] else None
        last_done_hours = last["hours_at_maintenance"] if last else None
        due = False
        overdue_label = None
        if p["interval_type"] == "days":
            if last_done_at:
                try:
                    last_date = datetime.datetime.strptime(last_done_at, "%Y-%m-%d").date()
                except ValueError:
                    last_date = None
                if last_date:
                    next_due = last_date + datetime.timedelta(days=p["interval_value"])
                    overdue_days = (today - next_due).days
                    if overdue_days >= 0:
                        due = True
                        overdue_label = f"เกินกำหนด {overdue_days} วัน" if overdue_days > 0 else "ครบกำหนดวันนี้"
            else:
                due = True
                overdue_label = "ยังไม่เคยทำ"
        else:  # hours
            hours_now = total_usage_hours or 0
            base_hours = last_done_hours if last_done_hours is not None else 0
            hours_since = hours_now - base_hours
            if hours_since >= p["interval_value"]:
                due = True
                if last_done_hours is None:
                    overdue_label = f"ยังไม่เคยทำ (สะสม {hours_now:.0f}/{p['interval_value']} ชม.)"
                else:
                    overdue_label = f"ใช้งานสะสม {hours_now:.0f} ชม. (เกินรอบ {p['interval_value']} ชม. ไป {hours_since - p['interval_value']:.0f} ชม.)"
        results.append({
            "plan_item_id": p["plan_item_id"], "task_name": p["task_name"],
            "device_type": p["device_type"], "interval_type": p["interval_type"],
            "interval_value": p["interval_value"], "last_done_at": last_done_at,
            "last_done_hours": last_done_hours, "due": due, "overdue_label": overdue_label,
        })
    results.sort(key=lambda x: 0 if x["due"] else 1)
    return results


def _device_overview_status(conn, device):
    """สถานะรวมของเครื่องนี้ (ใช้บน Dashboard ทั้งฝั่งลูกค้า/แอดมิน) — ลำดับความสำคัญ:
    'in_repair' (มีตั๋วซ่อมค้างอยู่) > 'maintenance_due' (ถึงรอบบำรุงรักษาอย่างน้อย 1 งาน) > 'ready' (พร้อมใช้งาน)"""
    open_ticket = conn.execute(
        """SELECT ticket_id, status FROM Tickets WHERE device_sn=? AND status != 'Resolved/Closed'
           ORDER BY created_at DESC LIMIT 1""",
        (device["device_sn"],),
    ).fetchone()
    tasks = _device_task_status(conn, device["device_sn"], device["type"], device["total_usage_hours"])
    due_tasks = [t for t in tasks if t["due"]]
    if open_ticket:
        overview = "in_repair"
    elif due_tasks:
        overview = "maintenance_due"
    else:
        overview = "ready"
    return {"status": overview, "open_ticket_id": open_ticket["ticket_id"] if open_ticket else None,
            "tasks": tasks, "due_tasks": due_tasks}


def _maintenance_due_devices(conn):
    """เครื่องที่ "ใช้งานอยู่" (status='Active') และมีอย่างน้อย 1 งานบำรุงรักษาตามแผนที่ถึง/เกินกำหนดแล้ว
    (คำนวณจาก Maintenance_Plan_Items ผ่าน _device_task_status — รองรับทั้งรอบแบบวันและแบบชั่วโมงใช้งานสะสม)
    เรียงเครื่องที่มีงานค้างมากสุดก่อน — เครื่องที่เลิกใช้แล้ว/ขายต่อแล้วจะไม่ปรากฏในนี้เลย ไม่จำกัดตามศูนย์บริการ
    เพราะเครื่องพิมพ์/ลูกค้าใช้ร่วมกันได้ทุกศูนย์ (เหมือนหน้าลูกค้า/เครื่อง)"""
    rows = conn.execute(
        """SELECT d.device_sn, d.model, d.type, d.total_usage_hours, c.name AS customer_name
           FROM Devices d JOIN Customers c ON c.customer_id = d.customer_id
           WHERE d.status = 'Active' ORDER BY d.device_sn"""
    ).fetchall()
    due = []
    for r in rows:
        due_tasks = [t for t in _device_task_status(conn, r["device_sn"], r["type"], r["total_usage_hours"]) if t["due"]]
        if due_tasks:
            due.append({
                "device_sn": r["device_sn"], "model": r["model"], "customer_name": r["customer_name"],
                "due_tasks": due_tasks, "due_count": len(due_tasks),
            })
    due.sort(key=lambda x: -x["due_count"])
    return due


# ------------------------------------------------------ Alert & Notification --
# แจ้งเตือนในระบบ (in-app, ดูที่ /notifications) ควบคู่กับพยายามส่งอีเมล (ถ้าตั้งค่า SMTP_* ไว้ — ดู db.py)
# เมื่อเครื่องถึงรอบบำรุงรักษา ระบบนี้ไม่มี background worker/cron จริง จึงเรียก _sync_maintenance_notifications()
# แบบ lazy ทุกครั้งที่มีคนเข้าหน้า Dashboard ที่เกี่ยวข้อง (ลูกค้า/แอดมิน/ผู้จัดการ) — กันแจ้งซ้ำงานเดิมด้วย
# plan_item_id (แจ้งครั้งเดียวต่อเครื่อง/งานบำรุงรักษา จนกว่าจะมีการบันทึกบำรุงรักษาใหม่ทำให้ครบกำหนดอีกรอบ)

def _send_email(to_addr, subject, body):
    """ส่งอีเมลผ่าน SMTP ตามค่าที่ตั้งไว้ใน environment variables (db.SMTP_*) — ถ้าไม่ได้ตั้งค่า SMTP_HOST ไว้
    หรือผู้รับไม่มีอีเมล จะข้ามการส่งไปเงียบๆ (คืน False, เหตุผล) โดยไม่ทำให้ระบบล้ม — การแจ้งเตือนในแอป (in-app)
    ยังคงถูกสร้างให้เสมอไม่ว่าจะส่งอีเมลได้หรือไม่"""
    if not db.SMTP_HOST:
        return False, "SMTP ยังไม่ได้ตั้งค่า (SMTP_HOST ว่าง) — ข้ามการส่งอีเมล"
    if not to_addr:
        return False, "ไม่มีอีเมลผู้รับ"
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = db.SMTP_FROM or db.SMTP_USER
        msg["To"] = to_addr
        with smtplib.SMTP(db.SMTP_HOST, db.SMTP_PORT, timeout=15) as server:
            if db.SMTP_USE_TLS:
                server.starttls()
            if db.SMTP_USER:
                server.login(db.SMTP_USER, db.SMTP_PASSWORD)
            server.sendmail(db.SMTP_FROM or db.SMTP_USER, [to_addr], msg.as_string())
        return True, None
    except Exception as e:  # noqa: BLE001 — กันทุก error จาก smtplib ไม่ให้ทำหน้า Dashboard ล่ม
        return False, f"{type(e).__name__}: {e}"


def _create_notification(conn, user_id, device_sn, plan_item_id, category, title, message, email_to=None):
    """สร้างการแจ้งเตือนในระบบ 1 รายการ พร้อมพยายามส่งอีเมลควบคู่กัน (ถ้ามี email_to และตั้งค่า SMTP ไว้)"""
    sent, error = (False, None)
    if email_to:
        sent, error = _send_email(email_to, title, message)
    conn.execute(
        """INSERT INTO Notifications (user_id, device_sn, plan_item_id, category, title, message,
                                       is_read, email_sent, email_error, created_at)
           VALUES (?,?,?,?,?,?,0,?,?,?)""",
        (user_id, device_sn, plan_item_id, category, title, message, 1 if sent else 0, error, db.now()),
    )


def _sync_customer_to_odoo(conn, customer_id):
    """ซิงก์ข้อมูลลูกค้า 1 คนไปยัง Odoo (res.partner) แบบอัตโนมัติทันทีหลังสร้าง/แก้ไขลูกค้าเสร็จ —
    ถ้าไม่ได้ตั้งค่า Odoo ไว้ (ดู db.ODOO_*) หรือเชื่อมต่อไม่สำเร็จ จะข้ามไปเงียบๆ ไม่ throw ออกไป
    (ดู odoo_client.py) เรียกใช้ "หลัง conn.commit() ของข้อมูลลูกค้าหลักเสร็จแล้วเท่านั้น" เพื่อไม่ให้
    ปัญหาฝั่ง Odoo ย้อนกลับมาทำให้การสร้าง/แก้ไขลูกค้าใน DB หลักต้อง rollback ไปด้วย"""
    row = conn.execute("SELECT * FROM Customers WHERE customer_id=?", (customer_id,)).fetchone()
    if not row:
        return
    partner_id = odoo_client.sync_customer(
        customer_id, row["name"], phone=row["phone"], email=row["email"],
        address=row["address"], tax_id=row["tax_id"], odoo_partner_id=row["odoo_partner_id"],
    )
    if partner_id and partner_id != row["odoo_partner_id"]:
        conn.execute("UPDATE Customers SET odoo_partner_id=? WHERE customer_id=?", (partner_id, customer_id))
        conn.commit()


def _sync_product_to_odoo(conn, sku):
    """ซิงก์สินค้า/อะไหล่ 1 รายการไปยัง Odoo (product.template) แบบอัตโนมัติทันทีหลังสร้าง/แก้ไขสินค้าเสร็จ
    — เรียกใช้หลัง conn.commit() ของข้อมูลสินค้าหลักเสร็จแล้วเท่านั้น (ดู _sync_customer_to_odoo ด้านบน
    สำหรับเหตุผลเดียวกัน — กันปัญหาฝั่ง Odoo ย้อนกลับมาทำให้ต้อง rollback ข้อมูลหลัก)"""
    row = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not row:
        return
    product_id = odoo_client.sync_product(
        row["part_sku"], row["part_name"], price=row["cost_price"], description=row["description"],
        category_label=PRODUCT_CATEGORY_LABELS.get(row["category"]), odoo_product_id=row["odoo_product_id"],
    )
    if product_id and product_id != row["odoo_product_id"]:
        conn.execute("UPDATE Spare_Parts SET odoo_product_id=? WHERE part_sku=?", (product_id, sku))
        conn.commit()


def _sync_staff_user_to_odoo(conn, user_id):
    """ซิงก์บัญชีพนักงาน/ทีมงานภายใน (ไม่ใช่ role='customer') ไปยัง Odoo (res.users) แบบอัตโนมัติทันที
    หลังสร้าง/แก้ไขบัญชีเสร็จ — ข้ามถ้าเป็นบัญชีลูกค้า (role='customer' ซิงก์แยกเป็น res.partner ผ่าน
    _sync_customer_to_odoo อยู่แล้ว ไม่ต้องมี res.users ซ้ำ)"""
    row = conn.execute("SELECT * FROM Users WHERE user_id=?", (user_id,)).fetchone()
    if not row or row["role"] == "customer":
        return
    odoo_user_id = odoo_client.sync_staff_user(
        user_id, row["username"], row["name"], phone=row["phone"], odoo_user_id=row["odoo_user_id"],
    )
    if odoo_user_id and odoo_user_id != row["odoo_user_id"]:
        conn.execute("UPDATE Users SET odoo_user_id=? WHERE user_id=?", (odoo_user_id, user_id))
        conn.commit()


def _sync_service_center_to_odoo(conn, center_id):
    """ซิงก์ศูนย์บริการพาร์ทเนอร์ 1 สาขาไปยัง Odoo (res.partner, is_company=1) แบบอัตโนมัติทันทีหลัง
    สร้าง/แก้ไขศูนย์บริการเสร็จ"""
    row = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
    if not row:
        return
    partner_id = odoo_client.sync_service_center(
        center_id, row["name"], address=row["address"], phone=row["phone"], tax_id=row["tax_id"],
        email=row["email"], website=row["website"], odoo_partner_id=row["odoo_partner_id"],
    )
    if partner_id and partner_id != row["odoo_partner_id"]:
        conn.execute("UPDATE Service_Centers SET odoo_partner_id=? WHERE center_id=?", (partner_id, center_id))
        conn.commit()


def _sync_maintenance_notifications(conn):
    """สแกนเครื่องที่ถึงรอบบำรุงรักษาทั้งหมด แล้วสร้างการแจ้งเตือนให้บัญชีลูกค้าเจ้าของเครื่อง (ถ้ามีบัญชี login)
    ทีละงาน — ข้ามงานที่เคยแจ้งเตือนไปแล้วและยังไม่ถูกทำ (กันแจ้งซ้ำทุกครั้งที่เข้าหน้า Dashboard)"""
    for d in _maintenance_due_devices(conn):
        device = conn.execute(
            "SELECT customer_id FROM Devices WHERE device_sn=?", (d["device_sn"],)
        ).fetchone()
        if not device:
            continue
        cust_user = conn.execute(
            "SELECT user_id FROM Users WHERE role='customer' AND customer_id=? AND is_active=1",
            (device["customer_id"],),
        ).fetchone()
        if not cust_user:
            continue
        customer = conn.execute(
            "SELECT email FROM Customers WHERE customer_id=?", (device["customer_id"],)
        ).fetchone()
        email_to = (customer["email"] if customer else None) or None
        for t in d["due_tasks"]:
            already = conn.execute(
                """SELECT 1 FROM Notifications WHERE user_id=? AND device_sn=? AND plan_item_id=?
                   AND category='maintenance_due' LIMIT 1""",
                (cust_user["user_id"], d["device_sn"], t["plan_item_id"]),
            ).fetchone()
            if already:
                continue
            title = f"🔧 ถึงรอบบำรุงรักษา: {d['model']} ({d['device_sn']})"
            message = f"งาน '{t['task_name']}' — {t['overdue_label']}"
            _create_notification(conn, cust_user["user_id"], d["device_sn"], t["plan_item_id"],
                                  "maintenance_due", title, message, email_to=email_to)
    conn.commit()


@route("GET", r"/notifications")
def notifications_inbox(environ, m, conn, user):
    """กล่องแจ้งเตือนในระบบ — ใช้ได้ทุกบทบาทที่ login แล้ว (ปัจจุบันมีเนื้อหาจริงเฉพาะบัญชีลูกค้า
    เพราะเป็นผู้รับการแจ้งเตือนบำรุงรักษาเครื่องของตัวเอง)"""
    require_login(user)
    if user["role"] == "customer":
        _sync_maintenance_notifications(conn)
    rows = conn.execute(
        "SELECT n.*, d.model FROM Notifications n LEFT JOIN Devices d ON d.device_sn = n.device_sn "
        "WHERE n.user_id=? ORDER BY n.created_at DESC LIMIT 200",
        (user["user_id"],),
    ).fetchall()
    return render("notifications.html", notifications=rows, user=user)


@route("POST", r"/notifications/(\d+)/read")
def notifications_mark_read(environ, m, conn, user):
    require_login(user)
    notif_id = int(m.group(1))
    conn.execute(
        "UPDATE Notifications SET is_read=1 WHERE notification_id=? AND user_id=?",
        (notif_id, user["user_id"]),
    )
    conn.commit()
    raise Redirect(environ.get("HTTP_REFERER") or "/notifications")


@route("POST", r"/notifications/read-all")
def notifications_mark_all_read(environ, m, conn, user):
    require_login(user)
    conn.execute("UPDATE Notifications SET is_read=1 WHERE user_id=? AND is_read=0", (user["user_id"],))
    conn.commit()
    raise Redirect("/notifications")


def _unread_notification_count(conn, user):
    if not user:
        return 0
    return conn.execute(
        "SELECT COUNT(*) c FROM Notifications WHERE user_id=? AND is_read=0", (user["user_id"],)
    ).fetchone()["c"]


# ------------------------------------------------------------------- Checklist --
# รายการตรวจสอบก่อนพิมพ์ทุกครั้ง (บังคับติ๊กครบก่อนเริ่มงานพิมพ์ได้ — ดู Print_Sessions ด้านล่าง)

def _checklist_items_for_type(conn, device_type, active_only=True):
    cond = " AND is_active=1" if active_only else ""
    return conn.execute(
        f"SELECT * FROM Checklist_Items WHERE (device_type=? OR device_type IS NULL){cond} "
        "ORDER BY sort_order, checklist_item_id",
        (device_type,),
    ).fetchall()


def _user_can_access_device(user, device):
    """staff (admin/manager/technician/sales) เข้าถึงเครื่องพิมพ์ได้ทุกเครื่อง (เหมือนหน้าลูกค้า/เครื่อง
    ที่ไม่ได้ scope ตามศูนย์บริการ) ส่วนลูกค้าเข้าถึงได้เฉพาะเครื่องของตัวเองเท่านั้น"""
    if not user or not device:
        return False
    if user["role"] in ("admin", "manager", "technician", "sales"):
        return True
    if user["role"] == "customer":
        return device["customer_id"] == user.get("customer_id")
    return False


def _device_home_url_for(user, device_sn):
    """ลิงก์กลับไปหน้าที่เหมาะสมตามบทบาทของผู้ใช้หลังบันทึกงานพิมพ์/บำรุงรักษาสำเร็จ"""
    if user["role"] == "customer":
        return "/customer/maintenance"
    return f"/device/{device_sn}/history"


@route("GET", r"/device/(.+)/print/new")
def device_print_checklist_form(environ, m, conn, user):
    """หน้า Checklist ก่อนเริ่มงานพิมพ์ — ลูกค้า (เจ้าของเครื่อง) หรือช่าง/staff กดยืนยันว่าตรวจเช็คแล้วก่อน
    บันทึก 'เริ่มงานพิมพ์' ได้ทุกครั้ง (บังคับติ๊กครบทุกข้อ) พร้อมกรอกชั่วโมงที่ประเมินว่าจะใช้พิมพ์งานนี้"""
    require_login(user)
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    if not _user_can_access_device(user, device):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงเครื่องพิมพ์นี้")
    checklist = _checklist_items_for_type(conn, device["type"])
    return render("device_print_checklist.html", device=device, checklist=checklist, user=user, error=None)


@route("POST", r"/device/(.+)/print/new")
def device_print_checklist_submit(environ, m, conn, user):
    require_login(user)
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    if not _user_can_access_device(user, device):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงเครื่องพิมพ์นี้")
    checklist = _checklist_items_for_type(conn, device["type"])
    form = parse_post(environ)

    def with_error(msg):
        return render("device_print_checklist.html", device=device, checklist=checklist, user=user, error=msg)

    # แต่ละข้อ Checklist ใช้ checkbox ชื่อ check_<checklist_item_id> แยกกัน (parse_post เก็บได้แค่ค่าเดียวต่อ
    # ชื่อฟิลด์ จึงตั้งชื่อแยกต่อข้อ แทนที่จะใช้ name="checklist_item_id" ซ้ำกันหลาย checkbox) — ต้องติ๊กครบทุกข้อ
    missing = [c for c in checklist if not form.get(f"check_{c['checklist_item_id']}")]
    if missing:
        return with_error("กรุณาติ๊กให้ครบทุกข้อในรายการตรวจสอบก่อนเริ่มงานพิมพ์")
    try:
        estimated_hours = float(form.get("estimated_hours") or 0)
    except ValueError:
        return with_error("ชั่วโมงที่ประเมินไม่ถูกต้อง")
    if estimated_hours < 0:
        return with_error("ชั่วโมงที่ประเมินต้องไม่ติดลบ")

    snapshot = json.dumps([c["label"] for c in checklist], ensure_ascii=False)
    conn.execute(
        """INSERT INTO Print_Sessions (device_sn, started_by, checklist_snapshot, estimated_hours, job_note, created_at)
           VALUES (?,?,?,?,?,?)""",
        (sn, user["user_id"], snapshot, estimated_hours, form.get("job_note", ""), db.now()),
    )
    if estimated_hours:
        conn.execute(
            "UPDATE Devices SET total_usage_hours = total_usage_hours + ? WHERE device_sn=?",
            (estimated_hours, sn),
        )
    conn.commit()
    raise Redirect(_device_home_url_for(user, sn))


# ------------------------------------------------------------- self-service บำรุงรักษา --
# ลูกค้าบำรุงรักษาเครื่องพิมพ์ของตัวเองได้เอง (ไม่ต้องรอช่าง) — เลือกงานตามแผน (ถ้ามี) หรือบันทึกอิสระก็ได้
# staff (admin/manager/technician) ก็ใช้หน้านี้บันทึกแทนลูกค้าได้เช่นกัน — ใช้ฟอร์มเดียวกันทุกบทบาท

@route("GET", r"/device/(.+)/maintenance/log")
def device_maintenance_log_form(environ, m, conn, user):
    require_login(user)
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    if not _user_can_access_device(user, device):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงเครื่องพิมพ์นี้")
    plan_items = _maintenance_plan_items_for_type(conn, device["type"])
    return render("device_maintenance_log.html", device=device, plan_items=plan_items, user=user, error=None,
                   today=db.now()[:10], interval_labels=db.MAINTENANCE_INTERVAL_TYPE_LABELS)


@route("POST", r"/device/(.+)/maintenance/log")
def device_maintenance_log_submit(environ, m, conn, user):
    require_login(user)
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    if not _user_can_access_device(user, device):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงเครื่องพิมพ์นี้")
    form = parse_post(environ)
    plan_items = _maintenance_plan_items_for_type(conn, device["type"])

    def with_error(msg):
        return render("device_maintenance_log.html", device=device, plan_items=plan_items, user=user, error=msg,
                       today=db.now()[:10], interval_labels=db.MAINTENANCE_INTERVAL_TYPE_LABELS)

    # ติ๊กได้หลายงานพร้อมกัน (checkbox แยกตาม plan_item_id — parse_post เก็บได้แค่ค่าแรกต่อ 1 name
    # เดียว ดังนั้นต้องตั้งชื่อ input ไม่ซ้ำกันต่องาน) — บันทึกครั้งเดียวสร้างประวัติแยกทีละงานที่ติ๊กไว้
    checked_plan_ids = [p["plan_item_id"] for p in plan_items if form.get(f"plan_{p['plan_item_id']}")]

    performed_at = form.get("performed_at") or db.now()[:10]
    hours_input = (form.get("hours_at_maintenance") or "").strip()
    if hours_input:
        try:
            hours_at_maintenance = float(hours_input)
        except ValueError:
            return with_error("ชั่วโมงใช้งานสะสมไม่ถูกต้อง")
    else:
        hours_at_maintenance = device["total_usage_hours"]  # ไม่กรอก = ใช้ชั่วโมงสะสมปัจจุบันของเครื่อง

    parts_replaced = form.get("parts_replaced", "")
    notes = form.get("notes", "")

    if checked_plan_ids:
        for plan_item_id in checked_plan_ids:
            conn.execute(
                """INSERT INTO Maintenance_Logs (device_sn, plan_item_id, performed_at, hours_at_maintenance,
                                                  parts_replaced, notes, performed_by)
                   VALUES (?,?,?,?,?,?,?)""",
                (sn, plan_item_id, performed_at, hours_at_maintenance, parts_replaced, notes, user["user_id"]),
            )
    else:
        # ไม่ได้ติ๊กงานไหนเลย — บันทึกอิสระไม่ผูกกับแผนงาน (plan_item_id = NULL) เหมือนเดิม
        conn.execute(
            """INSERT INTO Maintenance_Logs (device_sn, plan_item_id, performed_at, hours_at_maintenance,
                                              parts_replaced, notes, performed_by)
               VALUES (?,?,?,?,?,?,?)""",
            (sn, None, performed_at, hours_at_maintenance, parts_replaced, notes, user["user_id"]),
        )
    conn.commit()
    raise Redirect(f"/device/{sn}/history")


@route("GET", r"/device/(.+)/history")
def device_history(environ, m, conn, user):
    """ประวัติการทำงานของเครื่องพิมพ์เครื่องนี้ (History Log) — รวมประวัติบำรุงรักษา (ใครทำ เมื่อไหร่
    เปลี่ยนอะไหล่อะไรบ้าง) และประวัติเริ่มงานพิมพ์ (Checklist + ชั่วโมงที่ประเมิน) เรียงใหม่สุดก่อน
    พร้อมสถานะรวมของเครื่องและรายการงานบำรุงรักษาที่ครบกำหนดในตอนนี้"""
    require_login(user)
    sn = m.group(1)
    device = conn.execute(
        """SELECT d.*, c.name AS customer_name FROM Devices d
           JOIN Customers c ON c.customer_id = d.customer_id WHERE d.device_sn=?""",
        (sn,),
    ).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    if not _user_can_access_device(user, device):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงเครื่องพิมพ์นี้")
    overview = _device_overview_status(conn, device)
    maint_logs = conn.execute(
        """SELECT ml.*, pi.task_name, u.name AS performed_by_name
           FROM Maintenance_Logs ml
           LEFT JOIN Maintenance_Plan_Items pi ON pi.plan_item_id = ml.plan_item_id
           LEFT JOIN Users u ON u.user_id = ml.performed_by
           WHERE ml.device_sn=? ORDER BY ml.performed_at DESC, ml.maintenance_id DESC""",
        (sn,),
    ).fetchall()
    print_sessions = conn.execute(
        """SELECT ps.*, u.name AS started_by_name FROM Print_Sessions ps
           LEFT JOIN Users u ON u.user_id = ps.started_by
           WHERE ps.device_sn=? ORDER BY ps.created_at DESC, ps.session_id DESC""",
        (sn,),
    ).fetchall()
    print_sessions = [dict(p, checklist=json.loads(p["checklist_snapshot"]) if p["checklist_snapshot"] else [])
                       for p in print_sessions]
    return render("device_history.html", device=device, overview=overview, maint_logs=maint_logs,
                   print_sessions=print_sessions, user=user)


@route("GET", r"/admin/dashboard")
def admin_dashboard(environ, m, conn, user):
    require_login(user, "admin", "manager")
    is_manager = user["role"] == "manager"
    _sync_maintenance_notifications(conn)

    # ช่วงวันที่แสดงผล (ค่าเริ่มต้น 15 วันล่าสุด) — มีผลกับตัวเลข/รายการที่อิง "วันที่แจ้งซ่อม" เท่านั้น
    # (เช่น ตัวเลขสรุปตามสถานะ, ระยะเวลาซ่อมเฉลี่ย) ส่วนภาระงานช่าง/สต็อกใกล้หมด/คิวนัดหมาย/รอตรวจสอบการชำระ
    # เป็นข้อมูล "ปัจจุบัน ณ ตอนนี้" ไม่ผูกกับช่วงวันที่ที่เลือก
    from_sql, to_sql, from_display, to_display = days_date_range(environ, 15)

    # เลือกศูนย์บริการที่จะดู — ผู้จัดการผูกกับศูนย์ของบัญชีตัวเองเสมอ (เลือกเองไม่ได้ ป้องกันเห็นข้อมูลศูนย์อื่น)
    # ส่วนแอดมินเลือกได้อิสระผ่าน dropdown บนหน้า Dashboard (ค่าว่าง/ไม่เลือก = ดูรวมทุกศูนย์บริการ)
    if is_manager:
        scope_center = user.get("center_id")
    else:
        qs = parse_qs(environ.get("QUERY_STRING", ""))
        center_param = qs.get("center_id", [""])[0]
        scope_center = int(center_param) if center_param.isdigit() else None

    if scope_center:
        counts = conn.execute(
            "SELECT status, COUNT(*) c FROM Tickets WHERE center_id = ? AND created_at BETWEEN ? AND ? GROUP BY status",
            (scope_center, from_sql, to_sql),
        ).fetchall()
        workload = conn.execute(
            """SELECT u.name, sc.name AS center_name, COUNT(t.ticket_id) open_tickets FROM Users u
               LEFT JOIN Service_Centers sc ON sc.center_id = u.center_id
               LEFT JOIN Tickets t ON t.assigned_tech_id = u.user_id AND t.status != 'Resolved/Closed'
               WHERE u.role='technician' AND u.center_id = ? GROUP BY u.user_id, u.name, sc.name""",
            (scope_center,),
        ).fetchall()
        low_stock = conn.execute(
            """SELECT p.*, sc.name AS center_name FROM Spare_Parts p
               LEFT JOIN Service_Centers sc ON sc.center_id = p.center_id
               WHERE p.stock_quantity <= p.reorder_level AND (p.center_id = ? OR p.center_id IS NULL)""",
            (scope_center,),
        ).fetchall()
        centers_raw = conn.execute(
            "SELECT * FROM Service_Centers WHERE center_id = ?", (scope_center,)
        ).fetchall()
        customers_geo_raw = conn.execute(
            """SELECT DISTINCT c.customer_id, c.name, c.latitude, c.longitude,
                 (SELECT COUNT(*) FROM Devices dd WHERE dd.customer_id = c.customer_id) AS device_count
               FROM Customers c
               JOIN Devices d ON d.customer_id = c.customer_id
               JOIN Tickets t ON t.device_sn = d.device_sn
               WHERE t.center_id = ? AND c.latitude IS NOT NULL AND c.longitude IS NOT NULL""",
            (scope_center,),
        ).fetchall()
    else:
        counts = conn.execute(
            "SELECT status, COUNT(*) c FROM Tickets WHERE created_at BETWEEN ? AND ? GROUP BY status",
            (from_sql, to_sql),
        ).fetchall()
        workload = conn.execute(
            """SELECT u.name, sc.name AS center_name, COUNT(t.ticket_id) open_tickets FROM Users u
               LEFT JOIN Service_Centers sc ON sc.center_id = u.center_id
               LEFT JOIN Tickets t ON t.assigned_tech_id = u.user_id AND t.status != 'Resolved/Closed'
               WHERE u.role='technician' GROUP BY u.user_id, u.name, sc.name"""
        ).fetchall()
        low_stock = conn.execute(
            """SELECT p.*, sc.name AS center_name FROM Spare_Parts p
               LEFT JOIN Service_Centers sc ON sc.center_id = p.center_id
               WHERE p.stock_quantity <= p.reorder_level"""
        ).fetchall()
        centers_raw = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
        customers_geo_raw = conn.execute(
            """SELECT c.customer_id, c.name, c.latitude, c.longitude,
                 (SELECT COUNT(*) FROM Devices dd WHERE dd.customer_id = c.customer_id) AS device_count
               FROM Customers c
               WHERE c.latitude IS NOT NULL AND c.longitude IS NOT NULL"""
        ).fetchall()

    counts = {r["status"]: r["c"] for r in counts}

    # ศูนย์บริการทั้งหมด (สำหรับ dropdown เลือกศูนย์บนหน้า Dashboard — เฉพาะแอดมิน)
    all_centers_for_filter = conn.execute("SELECT center_id, name FROM Service_Centers ORDER BY name").fetchall() \
        if not is_manager else []

    # รายชื่อตั๋วแต่ละสถานะ (และตั๋วทั้งหมด) สโคปตามศูนย์บริการ+ช่วงวันที่เดียวกับ counts ด้านบน —
    # ใช้แสดง popup รายละเอียดเมื่อคลิกตัวเลขบนการ์ดสถานะแต่ละใบ
    dash_ticket_cond = " AND t.center_id = ?" if scope_center else ""
    dash_ticket_params = (scope_center,) if scope_center else ()
    dash_ticket_rows = conn.execute(
        f"""SELECT t.ticket_id, t.status, t.created_at, t.assigned_tech_id, d.model, c.name AS customer_name
            FROM Tickets t
            JOIN Devices d ON d.device_sn = t.device_sn
            JOIN Customers c ON c.customer_id = d.customer_id
            WHERE t.created_at BETWEEN ? AND ?{dash_ticket_cond}
            ORDER BY t.created_at DESC""",
        (from_sql, to_sql, *dash_ticket_params),
    ).fetchall()
    dash_cases_for_js = {s: [] for s in db.STATUSES}
    dash_cases_for_js["total"] = []
    dash_cases_for_js["unassigned"] = []  # งานค้าง — ยังไม่มอบหมายช่าง และยังไม่ปิดงาน (ดู "งานค้าง" การ์ดบน Dashboard)
    for r in dash_ticket_rows:
        item = {
            "ticket_id": r["ticket_id"], "model": r["model"], "customer_name": r["customer_name"],
            "status": r["status"], "status_label": db.STATUS_LABELS.get(r["status"], r["status"]),
            "date": r["created_at"],
        }
        dash_cases_for_js["total"].append(item)
        if r["status"] in dash_cases_for_js:
            dash_cases_for_js[r["status"]].append(item)
        if not r["assigned_tech_id"] and r["status"] != "Resolved/Closed":
            dash_cases_for_js["unassigned"].append(item)
    unassigned_count = len(dash_cases_for_js["unassigned"])

    # คิวนัดหมายที่จะถึง (จองคิวล่วงหน้า) — สโคปตามศูนย์บริการเดียวกัน แสดงเฉพาะนัดหมายวันนี้เป็นต้นไปที่ยังไม่ปิดงาน
    # เรียงตามวันที่นัด/ช่วงเวลา ใช้ตอบโจทย์ "แดชบอร์ดควรแสดงคิว" ของระบบจองคิวซ่อม
    dash_booking_cond = " AND t.center_id = ?" if scope_center else ""
    dash_booking_params = (scope_center,) if scope_center else ()
    upcoming_bookings = conn.execute(
        f"""SELECT t.ticket_id, t.booking_date, t.booking_time_slot, t.status, t.assigned_tech_id,
                   d.model, c.name AS customer_name, sc.name AS center_name, u.name AS tech_name
            FROM Tickets t
            JOIN Devices d ON d.device_sn = t.device_sn
            JOIN Customers c ON c.customer_id = d.customer_id
            LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
            LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
            WHERE t.channel = 'booking' AND t.booking_date >= ? AND t.status != 'Resolved/Closed'{dash_booking_cond}
            ORDER BY t.booking_date, t.booking_time_slot""",
        (db.now()[:10], *dash_booking_params),
    ).fetchall()

    # รายการแจ้งชำระเงินที่รอตรวจสอบ (สโคปตามศูนย์บริการเช่นเดียวกัน) — ใช้ทั้งนับจำนวนบนการ์ด
    # "รอตรวจสอบการชำระ" และแสดง popup ให้ยืนยัน/ปฏิเสธได้ทันทีจากหน้า Dashboard
    dash_pay_cond = " AND t.center_id = ?" if scope_center else ""
    dash_pay_params = (scope_center,) if scope_center else ()
    pending_payments_raw = conn.execute(
        f"""SELECT p.payment_id, p.ticket_id, p.amount, p.slip_filename, p.created_at,
                   c.name AS customer_name, d.model
            FROM Payments p
            JOIN Tickets t ON t.ticket_id = p.ticket_id
            JOIN Devices d ON d.device_sn = t.device_sn
            JOIN Customers c ON c.customer_id = d.customer_id
            WHERE p.status = 'pending'{dash_pay_cond}
            ORDER BY p.created_at""",
        dash_pay_params,
    ).fetchall()
    pending_payments_count = len(pending_payments_raw)
    pending_payments_for_js = [
        {
            "ticket_id": p["ticket_id"], "payment_id": p["payment_id"], "model": p["model"],
            "customer_name": p["customer_name"], "amount": p["amount"],
            "slip_url": f"/media/{p['ticket_id']}/{p['slip_filename']}", "date": p["created_at"],
        }
        for p in pending_payments_raw
    ]

    # รายการที่ต้องทำเร่งด่วนวันนี้ — รวม 3 ประเภทงานค้างที่ต้องรีบดำเนินการ: นัดหมายวันนี้ที่ยังไม่เริ่มงาน,
    # ตั๋วที่ยังไม่มอบหมายช่าง, และแจ้งชำระเงินที่รอตรวจสอบ — เรียงตามความเร่งด่วน จำกัด 8 รายการบนสุด
    dash_todo = []
    for b in upcoming_bookings:
        if b["booking_date"] == db.now()[:10] and b["status"] == "New":
            dash_todo.append({
                "icon": "🗓️", "title": f"ยืนยันนัดหมายวันนี้ #{b['ticket_id']}",
                "subtitle": f"นัด {b['booking_time_slot']} · {b['customer_name']} · {b['model']}",
                "url": f"/admin/ticket/{b['ticket_id']}",
            })
    for item in dash_cases_for_js["unassigned"][:5]:
        dash_todo.append({
            "icon": "🧑‍🔧", "title": f"มอบหมายช่างให้งาน #{item['ticket_id']}",
            "subtitle": f"{item['customer_name']} · {item['model']} · แจ้งเมื่อ {item['date']}",
            "url": f"/admin/ticket/{item['ticket_id']}",
        })
    for p in pending_payments_for_js[:5]:
        dash_todo.append({
            "icon": "💳", "title": f"ยืนยันการชำระเงิน #{p['ticket_id']}",
            "subtitle": f"{p['customer_name']} · {p['amount']:,.0f} บาท",
            "url": f"/admin/ticket/{p['ticket_id']}",
        })
    dash_todo = dash_todo[:8]

    centers = annotate_centers(centers_raw)
    centers_with_geo = [c for c in centers if c["latitude"] is not None and c["longitude"] is not None]
    customers_with_geo = list(customers_geo_raw)

    # เติม popup_html ให้แต่ละหมุด เพื่อให้คลิกแล้วเห็นรายละเอียดศูนย์บริการ (ผู้จัดการ/เซล/ทีมช่าง/คิวงาน)
    # และรายละเอียดลูกค้า (เครื่องพิมพ์ทั้งหมด + สถานะซ่อมล่าสุด) ได้ทันทีโดยไม่ต้องออกจากหน้า Dashboard
    center_ov = _center_overview_map(conn, [c["center_id"] for c in centers_with_geo])
    centers_with_geo = [dict(c, popup_html=_map_center_popup(c, center_ov.get(c["center_id"])))
                         for c in centers_with_geo]
    customer_devs = _customer_devices_map(conn, [cu["customer_id"] for cu in customers_with_geo])
    customers_with_geo = [dict(cu, popup_html=_map_customer_popup(cu, customer_devs.get(cu["customer_id"], [])))
                           for cu in customers_with_geo]

    if is_manager:
        scope_label = centers[0]["name"] if centers else "ยังไม่ได้กำหนดศูนย์บริการให้บัญชีนี้ — กรุณาติดต่อแอดมิน"
    elif scope_center:
        scope_label = centers[0]["name"] if centers else "ทุกศูนย์บริการ"
    else:
        scope_label = "ทุกศูนย์บริการ"

    # เครื่องที่ครบกำหนดบำรุงรักษาเดือนนี้ — ไม่จำกัดตามศูนย์บริการ (เหมือนหน้าลูกค้า/เครื่อง เพราะใช้ร่วมกันได้ทุกศูนย์)
    maintenance_due = _maintenance_due_devices(conn)

    # กราฟเส้นแนวโน้มรายเดือนบนสุดของ Dashboard — ยอดขายเครื่องพิมพ์ FDM/Resin, จำนวนเคสที่แจ้งซ่อม/ปิดงาน,
    # และค่าแรงช่างรวม ย้อนหลัง DASHBOARD_TREND_MONTHS เดือน (รวมเดือนปัจจุบัน) สโคปตามศูนย์บริการแบบเดียวกับส่วนอื่นของหน้านี้
    dash_labels = _last_n_months_labels(DASHBOARD_TREND_MONTHS)
    dash_since = dash_labels[0] + "-01 00:00:00"
    center_cond = " AND so.center_id = ?" if scope_center else ""
    center_params = [scope_center] if scope_center else []

    fdm_rows = conn.execute(
        f"""SELECT so.created_at, si.quantity * si.unit_price AS revenue
            FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
            JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
            WHERE sp.category = 'FDM_Printer' AND so.created_at >= ?{center_cond}""",
        (dash_since, *center_params),
    ).fetchall()
    resin_rows = conn.execute(
        f"""SELECT so.created_at, si.quantity * si.unit_price AS revenue
            FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
            JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
            WHERE sp.category = 'Resin_Printer' AND so.created_at >= ?{center_cond}""",
        (dash_since, *center_params),
    ).fetchall()
    material_rows = conn.execute(
        f"""SELECT so.created_at, si.quantity * si.unit_price AS revenue
            FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
            JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
            WHERE sp.category = 'Material' AND so.created_at >= ?{center_cond}""",
        (dash_since, *center_params),
    ).fetchall()

    ticket_center_cond = " AND center_id = ?" if scope_center else ""
    ticket_center_params = [scope_center] if scope_center else []
    tickets_created_rows = conn.execute(
        f"SELECT created_at FROM Tickets WHERE created_at >= ?{ticket_center_cond}",
        (dash_since, *ticket_center_params),
    ).fetchall()
    tickets_closed_rows = conn.execute(
        f"""SELECT closed_at FROM Tickets
            WHERE status = 'Resolved/Closed' AND closed_at >= ?{ticket_center_cond}""",
        (dash_since, *ticket_center_params),
    ).fetchall()

    # ระยะเวลาซ่อมเฉลี่ย (วัน) — เฉลี่ยจาก created_at ถึง closed_at ของตั๋วที่ปิดงานแล้วในช่วงวันที่ที่เลือกไว้ด้านบน
    # (from_sql/to_sql ค่าเริ่มต้น 15 วันล่าสุด) ใช้แสดงบนการ์ดสถิติ "ระยะเวลาซ่อมเฉลี่ย" บน Dashboard
    repair_duration_rows = conn.execute(
        f"""SELECT created_at, closed_at FROM Tickets
            WHERE status = 'Resolved/Closed' AND closed_at BETWEEN ? AND ?{ticket_center_cond}""",
        (from_sql, to_sql, *ticket_center_params),
    ).fetchall()
    _durations = []
    for r in repair_duration_rows:
        try:
            created = datetime.datetime.strptime(r["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            closed = datetime.datetime.strptime(r["closed_at"][:19], "%Y-%m-%d %H:%M:%S")
            _durations.append((closed - created).total_seconds() / 86400)
        except (TypeError, ValueError):
            continue
    avg_repair_days = round(sum(_durations) / len(_durations), 1) if _durations else None

    labor_center_cond = " AND t.center_id = ?" if scope_center else ""
    labor_center_params = [scope_center] if scope_center else []
    labor_rows = conn.execute(
        f"""SELECT sl.created_at, sl.labor_fee FROM Service_Logs sl
            JOIN Tickets t ON t.ticket_id = sl.ticket_id
            WHERE sl.created_at >= ?{labor_center_cond}""",
        (dash_since, *labor_center_params),
    ).fetchall()

    # จัดกลุ่มอะไหล่ใกล้หมดสต็อกตามประเภทสินค้า (เครื่องพิมพ์ FDM/Resin, อะไหล่, วัสดุพิมพ์, อื่นๆ) —
    # แยกตารางคนละใบต่อประเภทตามที่ขอ ข้ามประเภทที่ไม่มีรายการใกล้หมดสต็อกเลย
    low_stock_by_category = []
    for cat in PRODUCT_CATEGORIES:
        cat_parts = [p for p in low_stock if p["category"] == cat]
        if cat_parts:
            low_stock_by_category.append({
                "category": cat,
                "label": PRODUCT_CATEGORY_LABELS.get(cat, cat),
                "icon": PRODUCT_CATEGORY_ICONS.get(cat, "📦"),
                "parts": cat_parts,
            })

    dash_chart_fdm = _monthly_sum(fdm_rows, "created_at", "revenue", dash_labels)
    dash_chart_resin = _monthly_sum(resin_rows, "created_at", "revenue", dash_labels)
    dash_chart_material = _monthly_sum(material_rows, "created_at", "revenue", dash_labels)
    dash_chart_tickets_created = _monthly_count(tickets_created_rows, "created_at", dash_labels)
    dash_chart_tickets_closed = _monthly_count(tickets_closed_rows, "closed_at", dash_labels)
    dash_chart_labor = _monthly_sum(labor_rows, "created_at", "labor_fee", dash_labels)

    return render("admin_dashboard.html", counts=counts, workload=workload,
                   low_stock=low_stock, low_stock_by_category=low_stock_by_category,
                   user=user, total=sum(counts.values()),
                   maintenance_due=maintenance_due,
                   centers=centers, centers_with_geo=centers_with_geo, scope_label=scope_label,
                   customers_with_geo=customers_with_geo,
                   dash_chart_labels=dash_labels, dash_chart_fdm=dash_chart_fdm,
                   dash_chart_resin=dash_chart_resin,
                   dash_chart_material=dash_chart_material,
                   dash_chart_tickets_created=dash_chart_tickets_created,
                   dash_chart_tickets_closed=dash_chart_tickets_closed,
                   dash_chart_labor=dash_chart_labor,
                   dash_cases_for_js=dash_cases_for_js,
                   pending_payments_count=pending_payments_count,
                   pending_payments_for_js=pending_payments_for_js,
                   unassigned_count=unassigned_count,
                   upcoming_bookings=upcoming_bookings,
                   today_iso=db.now()[:10],
                   today_bookings_count=sum(1 for b in upcoming_bookings if b["booking_date"] == db.now()[:10]),
                   avg_repair_days=avg_repair_days,
                   open_tickets_count=sum(v for k, v in counts.items() if k != "Resolved/Closed"),
                   dash_todo=dash_todo,
                   date_from=from_display, date_to=to_display,
                   all_centers_for_filter=all_centers_for_filter,
                   selected_center_id=scope_center if not is_manager else None)


@route("GET", r"/admin/board")
def admin_board(environ, m, conn, user):
    require_login(user, "admin", "manager")
    is_manager = user["role"] == "manager"
    scope_center = user.get("center_id") if is_manager else None
    from_sql, to_sql, from_display, to_display = month_date_range(environ)

    if is_manager:
        tickets = conn.execute(
            """SELECT t.*, d.model, c.name AS customer_name, u.name AS tech_name, sc.name AS center_name
               FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
               LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
               WHERE t.center_id = ? AND t.created_at BETWEEN ? AND ?
               ORDER BY t.created_at""",
            (scope_center, from_sql, to_sql),
        ).fetchall()
        techs = conn.execute(
            "SELECT * FROM Users WHERE role='technician' AND center_id = ?", (scope_center,)
        ).fetchall()
    else:
        tickets = conn.execute(
            """SELECT t.*, d.model, c.name AS customer_name, u.name AS tech_name, sc.name AS center_name
               FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
               LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
               WHERE t.created_at BETWEEN ? AND ?
               ORDER BY t.created_at""",
            (from_sql, to_sql),
        ).fetchall()
        techs = conn.execute("SELECT * FROM Users WHERE role='technician'").fetchall()

    board = {s: [] for s in db.STATUSES}
    for t in tickets:
        board[t["status"]].append(t)
    return render("admin_board.html", board=board, techs=techs, user=user,
                   date_from=from_display, date_to=to_display)


def _staff_new_ticket_context(conn, user):
    """เตรียมข้อมูลสำหรับหน้า 'แจ้งซ่อมใหม่' ที่เจ้าหน้าที่ (admin/manager/sales) ใช้แจ้งซ่อมแทนลูกค้า —
    รายชื่อลูกค้าทั้งหมด (สำหรับ popup ค้นหา), เครื่องพิมพ์ของลูกค้าแต่ละราย (สำหรับเติม dropdown อัตโนมัติ
    ตอนเลือกลูกค้าแล้ว), และสาขาที่รับซ่อมได้ — admin เลือกสาขาได้เอง ส่วน manager/sales ผูกกับสาขาของ
    บัญชีตัวเองเท่านั้น (เหมือนรูปแบบเดียวกับหน้าบันทึกการขาย)"""
    customers = conn.execute("SELECT * FROM Customers ORDER BY name").fetchall()
    customers_for_js = [
        {"id": c["customer_id"], "name": c["name"], "phone": c["phone"] or "", "tax_id": c["tax_id"] or ""}
        for c in customers
    ]
    devices_raw = conn.execute("SELECT * FROM Devices WHERE status='Active' ORDER BY model").fetchall()
    open_sns = _open_ticket_device_sns(conn)
    devices_by_customer_for_js = {}
    for d in devices_raw:
        devices_by_customer_for_js.setdefault(d["customer_id"], []).append(
            {"sn": d["device_sn"], "model": d["model"], "has_open_ticket": d["device_sn"] in open_sns}
        )
    centers_all = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
    repair_centers = [c for c in centers_all if c["supports_fdm"] or c["supports_resin"]]

    fixed_center = None
    blocked_reason = None
    if user["role"] == "admin":
        if not repair_centers:
            blocked_reason = "none_repair"
    else:
        my_center_id = user.get("center_id")
        if not my_center_id:
            blocked_reason = "unassigned"
        else:
            fixed_center = next((c for c in repair_centers if c["center_id"] == my_center_id), None)
            if not fixed_center:
                blocked_reason = "not_repair"

    return dict(customers=customers, customers_for_js=customers_for_js,
                devices_by_customer_for_js=devices_by_customer_for_js,
                repair_centers=repair_centers, fixed_center=fixed_center, blocked_reason=blocked_reason)


@route("GET", r"/admin/ticket/new")
def staff_new_ticket_form(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    ctx = _staff_new_ticket_context(conn, user)
    return render("admin_new_ticket.html", user=user, error=None,
                   max_images=MAX_IMAGES, max_video_mb=MAX_VIDEO_MB, booking_time_slots=BOOKING_TIME_SLOTS, **ctx)


@route("POST", r"/admin/ticket/new")
def staff_new_ticket_submit(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    fields, files = parse_multipart(environ)
    customer_id = fields.get("customer_id") or ""
    device_sn = fields.get("device_sn", "")

    def with_error(msg):
        ctx = _staff_new_ticket_context(conn, user)
        return render("admin_new_ticket.html", user=user, error=msg,
                       max_images=MAX_IMAGES, max_video_mb=MAX_VIDEO_MB, booking_time_slots=BOOKING_TIME_SLOTS, **ctx)

    owned = conn.execute(
        "SELECT 1 FROM Devices WHERE device_sn=? AND customer_id=? AND status='Active'",
        (device_sn, customer_id),
    ).fetchone()
    if not owned:
        return with_error("กรุณาเลือกลูกค้าและเครื่องพิมพ์ให้ถูกต้อง")

    open_ticket = conn.execute(
        "SELECT ticket_id FROM Tickets WHERE device_sn=? AND status != 'Resolved/Closed'", (device_sn,)
    ).fetchone()
    if open_ticket:
        return with_error(
            f"เครื่องนี้มีตั๋วซ่อม #{open_ticket['ticket_id']} ที่ยังไม่เสร็จอยู่แล้ว "
            "กรุณารอให้ซ่อมเสร็จก่อน จึงจะแจ้งซ่อมเครื่องนี้ใหม่ได้"
        )

    if user["role"] == "admin":
        center_id = fields.get("center_id") or None
        if not center_id:
            return with_error("กรุณาเลือกสาขาที่รับผิดชอบงานซ่อมนี้")
        center_ok = conn.execute(
            "SELECT 1 FROM Service_Centers WHERE center_id=? AND (supports_fdm=1 OR supports_resin=1)",
            (center_id,),
        ).fetchone()
        if not center_ok:
            return with_error("สาขาที่เลือกไม่รับซ่อม กรุณาเลือกสาขาอื่น")
    else:
        # manager/sales ผูกกับสาขาของบัญชีตัวเองเสมอ — ไม่ใช้ค่าที่ส่งมาจากฟอร์ม ป้องกันการปลอมสาขา
        center_id = user.get("center_id")
        if not center_id:
            return with_error("บัญชีของคุณยังไม่ได้ถูกกำหนดศูนย์บริการ กรุณาติดต่อผู้ดูแลระบบ")
        center_ok = conn.execute(
            "SELECT 1 FROM Service_Centers WHERE center_id=? AND (supports_fdm=1 OR supports_resin=1)",
            (center_id,),
        ).fetchone()
        if not center_ok:
            return with_error("ศูนย์บริการของคุณยังไม่เปิดรับซ่อม กรุณาติดต่อผู้ดูแลระบบ")

    channel, booking_date, booking_time_slot, booking_err = _parse_booking_fields(fields)
    if booking_err:
        return with_error(booking_err)

    images = files.get("images", [])
    videos = files.get("video", [])

    if len(images) > MAX_IMAGES:
        return with_error(f"อัปโหลดรูปภาพได้สูงสุด {MAX_IMAGES} รูป (เลือกมา {len(images)} รูป)")
    for f in images:
        if not f["content_type"].startswith("image/"):
            return with_error(f"ไฟล์ '{f['filename']}' ไม่ใช่ไฟล์รูปภาพที่รองรับ")

    if len(videos) > 1:
        return with_error("อัปโหลดวิดีโอได้สูงสุด 1 คลิป")
    video = videos[0] if videos else None
    if video:
        if not video["content_type"].startswith("video/"):
            return with_error(f"ไฟล์ '{video['filename']}' ไม่ใช่ไฟล์วิดีโอที่รองรับ")
        if len(video["data"]) > MAX_VIDEO_BYTES:
            size_mb = round(len(video["data"]) / (1024 * 1024), 1)
            return with_error(f"ไฟล์วิดีโอขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_VIDEO_MB} MB)")

    cur = conn.execute(
        """INSERT INTO Tickets (device_sn, issue_category, description, center_id, status, created_at,
                                 channel, booking_date, booking_time_slot)
           VALUES (?,?,?,?, 'New', ?,?,?,?)""",
        (device_sn, fields.get("issue_category", ""), fields.get("description", ""), center_id, db.now(),
         channel, booking_date, booking_time_slot),
    )
    ticket_id = cur.lastrowid
    note = f"เจ้าหน้าที่ ({user['name']}) จองคิวให้ลูกค้า วันที่ {booking_date} ช่วง {booking_time_slot}" \
        if channel == "booking" else f"เจ้าหน้าที่ ({user['name']}) แจ้งซ่อมแทนลูกค้า"
    _log_status_history(conn, ticket_id, None, "New", user["user_id"], note=note)

    if images or video:
        ticket_dir = os.path.join(UPLOADS_DIR, str(ticket_id))
        os.makedirs(ticket_dir, exist_ok=True)
        for idx, f in enumerate(images, start=1):
            stored = f"img{idx}_{safe_filename(f['filename'])}"
            with open(os.path.join(ticket_dir, stored), "wb") as out:
                out.write(f["data"])
            conn.execute(
                "INSERT INTO Ticket_Media (ticket_id, media_type, filename, stored_name, uploaded_at) VALUES (?,?,?,?,?)",
                (ticket_id, "image", f["filename"], stored, db.now()),
            )
        if video:
            stored = f"video_{safe_filename(video['filename'])}"
            with open(os.path.join(ticket_dir, stored), "wb") as out:
                out.write(video["data"])
            conn.execute(
                "INSERT INTO Ticket_Media (ticket_id, media_type, filename, stored_name, uploaded_at) VALUES (?,?,?,?,?)",
                (ticket_id, "video", video["filename"], stored, db.now()),
            )

    conn.commit()
    raise Redirect(f"/admin/ticket/{ticket_id}")


@route("GET", r"/admin/ticket/(\d+)")
def admin_ticket_detail(environ, m, conn, user):
    require_login(user, "admin", "manager")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, d.type AS device_type, d.warranty_end_date,
                  c.name AS customer_name, c.phone, c.email, u.name AS tech_name, sc.name AS center_name
           FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    require_center_access(user, t["center_id"])
    media = conn.execute(
        "SELECT * FROM Ticket_Media WHERE ticket_id=? AND service_log_id IS NULL ORDER BY media_id", (ticket_id,)
    ).fetchall()
    logs = _service_logs_with_media(conn, ticket_id)
    if user["role"] == "manager":
        techs = conn.execute(
            "SELECT * FROM Users WHERE role='technician' AND is_active=1 AND center_id=?",
            (user.get("center_id"),),
        ).fetchall()
    else:
        techs = conn.execute("SELECT * FROM Users WHERE role='technician' AND is_active=1").fetchall()
    quotes = get_quotes_for_ticket(conn, ticket_id)
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    payments = get_payments_for_ticket(conn, ticket_id)
    centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
    status_history = _ticket_status_history(conn, ticket_id)
    # ให้ admin บันทึกผลการซ่อม/เบิกอะไหล่ได้เหมือนช่าง — ใช้ตัวเลือกอะไหล่ชุดเดียวกับหน้าช่าง (เฉพาะหมวด "อะไหล่")
    parts = conn.execute("SELECT * FROM Spare_Parts WHERE category='Spare_Part' ORDER BY part_name").fetchall()
    parts_for_js = [
        {
            "sku": p["part_sku"],
            "name": p["part_name"],
            "label": f"{p['part_name']} ({p['part_sku']})",
            "stock": p["stock_quantity"],
            "cost": p["cost_price"],
            "labor": p["labor_fee"],
        }
        for p in parts
    ]
    part_name_lookup = {p["part_sku"]: p["part_name"] for p in conn.execute(
        "SELECT part_sku, part_name FROM Spare_Parts"
    ).fetchall()}
    return render("admin_ticket_detail.html", t=t, media=media, logs=logs, techs=techs, user=user,
                   quotes=quotes, invoice_items=invoice_items, invoice_total=invoice_total, payments=payments,
                   centers=centers, status_history=status_history, parts=parts, parts_for_js=parts_for_js,
                   part_name_lookup=part_name_lookup)


@route("POST", r"/admin/ticket/(\d+)/update")
def admin_ticket_update(environ, m, conn, user):
    require_login(user, "admin", "manager")
    ticket_id = int(m.group(1))
    existing = conn.execute(
        "SELECT center_id, status, assigned_tech_id FROM Tickets WHERE ticket_id=?", (ticket_id,)
    ).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    require_center_access(user, existing["center_id"])
    form = parse_post(environ)
    status = form.get("status")
    tech_id = form.get("assigned_tech_id") or None
    closed_at = db.now() if status == "Resolved/Closed" else None
    if closed_at:
        conn.execute(
            "UPDATE Tickets SET status=?, assigned_tech_id=?, closed_at=? WHERE ticket_id=?",
            (status, tech_id, closed_at, ticket_id),
        )
    else:
        conn.execute(
            "UPDATE Tickets SET status=?, assigned_tech_id=? WHERE ticket_id=?",
            (status, tech_id, ticket_id),
        )

    # บันทึกประวัติ — เฉพาะตอนสถานะเปลี่ยนจริง หรือมอบหมาย/เปลี่ยนช่างใหม่ (กันบันทึกซ้ำเวลากดบันทึกฟอร์มโดยไม่ได้แก้อะไร)
    old_tech_id = existing["assigned_tech_id"]
    tech_id_int = int(tech_id) if tech_id else None
    if status != existing["status"] or tech_id_int != old_tech_id:
        note = None
        if tech_id_int != old_tech_id:
            tech_name = None
            if tech_id_int:
                tech_row = conn.execute("SELECT name FROM Users WHERE user_id=?", (tech_id_int,)).fetchone()
                tech_name = tech_row["name"] if tech_row else None
            note = f"มอบหมายช่าง: {tech_name}" if tech_name else "ยกเลิกการมอบหมายช่าง"
        _log_status_history(conn, ticket_id, existing["status"], status, user["user_id"], note=note)

    conn.commit()
    raise Redirect(form.get("next") or "/admin/board")


@route("POST", r"/admin/ticket/(\d+)/edit")
def admin_ticket_edit(environ, m, conn, user):
    require_login(user, "admin", "manager")
    ticket_id = int(m.group(1))
    existing = conn.execute("SELECT center_id FROM Tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    require_center_access(user, existing["center_id"])
    form = parse_post(environ)
    center_id = form.get("center_id") or None
    if center_id:
        center_ok = conn.execute("SELECT 1 FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
        if not center_ok:
            raise HttpError(400, "สาขาที่เลือกไม่ถูกต้อง")
        require_center_access(user, int(center_id))
    conn.execute(
        "UPDATE Tickets SET issue_category=?, description=?, center_id=? WHERE ticket_id=?",
        (form.get("issue_category", ""), form.get("description", ""), center_id, ticket_id),
    )
    conn.commit()
    raise Redirect(f"/admin/ticket/{ticket_id}")


@route("POST", r"/admin/ticket/(\d+)/delete")
def admin_ticket_delete(environ, m, conn, user):
    require_login(user, "admin", "manager")
    ticket_id = int(m.group(1))
    existing = conn.execute("SELECT center_id FROM Tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    require_center_access(user, existing["center_id"])
    _delete_ticket_cascade(conn, ticket_id)
    conn.commit()
    form = parse_post(environ)
    raise Redirect(form.get("next") or "/admin/board")


@route("GET", r"/admin/customers")
def admin_customers(environ, m, conn, user):
    # sales เข้าดูหน้านี้ได้ด้วย (เพิ่มลูกค้า/เพิ่ม-แก้ไขเครื่องได้ แต่ลบเครื่อง/แก้ไขลูกค้าไม่ได้ —
    # จำกัดสิทธิ์จริงในแต่ละ route ย่อยด้านล่าง และซ่อนปุ่มที่ไม่มีสิทธิ์ในเทมเพลต)
    require_login(user, "admin", "manager", "sales")
    # ข้อมูลลูกค้า/เครื่องพิมพ์ใช้ร่วมกันได้ทุกศูนย์บริการ (ลูกค้าคนเดียวกันอาจเข้ารับบริการ
    # ต่างศูนย์กันได้) จึงไม่จำกัดขอบเขตตามศูนย์ของผู้จัดการ — ผู้จัดการทุกคนเห็นรายชื่อ
    # ลูกค้า/เครื่องพิมพ์ทั้งหมดเหมือนแอดมิน (ต่างจากคิวงานซ่อม/สต็อกที่ยังคงแบ่งตามศูนย์)
    customers_raw = conn.execute("SELECT * FROM Customers ORDER BY customer_id").fetchall()
    # จำนวนเครื่องพิมพ์ที่ลงทะเบียนแล้วของลูกค้าแต่ละคน (นับทุกสถานะ) — แสดงคู่กับโควตาในตารางลูกค้า
    device_counts = {r["customer_id"]: r["c"] for r in conn.execute(
        "SELECT customer_id, COUNT(*) AS c FROM Devices GROUP BY customer_id"
    ).fetchall()}
    customers = [dict(c, device_count=device_counts.get(c["customer_id"], 0)) for c in customers_raw]
    # เรียงเครื่องที่เพิ่งลงทะเบียนล่าสุดขึ้นก่อน (created_at DESC) เพื่อให้เครื่องที่เพิ่งเพิ่ม
    # ปรากฏในหน้าแรกของตาราง (ตารางแบ่งหน้าสูงสุด 10 แถว/หน้า) — เครื่องเก่าที่ไม่มี created_at (NULL) จะอยู่ท้ายสุด
    devices_raw = conn.execute("SELECT * FROM Devices ORDER BY created_at DESC, customer_id").fetchall()
    devices = []
    for d in devices_raw:
        last = conn.execute(
            "SELECT MAX(performed_at) AS last_maintenance FROM Maintenance_Logs WHERE device_sn=?",
            (d["device_sn"],),
        ).fetchone()
        devices.append(dict(d, last_maintenance=last["last_maintenance"] if last else None))
    # ใช้เป็นข้อมูลค้นหาลูกค้าแบบ popup ตอนลงทะเบียนเครื่องพิมพ์ใหม่ (ลูกค้าอาจมีจำนวนมาก ไม่เหมาะกับ dropdown ยาวๆ)
    customers_for_js = [
        {"id": c["customer_id"], "name": c["name"], "phone": c["phone"] or "", "tax_id": c["tax_id"] or ""}
        for c in customers
    ]
    return render("admin_customers.html", customers=customers, devices=devices, user=user,
                   days_left=days_left, today=db.now()[:10], customers_for_js=customers_for_js)


def _parse_latlng(form):
    """แปลงพิกัดละติจูด/ลองจิจูดจากฟอร์ม — คืน (lat, lng, error_message_or_None)
    ถ้าไม่ได้กรอกทั้งคู่ ถือว่าไม่ระบุพิกัด (None, None, None) — ไม่บังคับกรอก"""
    lat_raw = (form.get("latitude") or "").strip()
    lng_raw = (form.get("longitude") or "").strip()
    if not lat_raw and not lng_raw:
        return None, None, None
    try:
        return float(lat_raw), float(lng_raw), None
    except ValueError:
        return None, None, "พิกัด (ละติจูด/ลองจิจูด) ต้องเป็นตัวเลข"


def _parse_device_quota(form, default=None):
    """แปลงค่าโควตาเครื่องพิมพ์จากฟอร์ม — ปล่อยว่าง/ค่าไม่ถูกต้อง จะใช้ default (หรือค่าเริ่มต้นของระบบ)
    ป้องกันค่าติดลบ (อย่างน้อย 0)"""
    raw = (form.get("device_quota") or "").strip()
    if not raw:
        return default if default is not None else db.DEFAULT_DEVICE_QUOTA
    try:
        return max(0, int(raw))
    except ValueError:
        return default if default is not None else db.DEFAULT_DEVICE_QUOTA


@route("POST", r"/admin/customers/new")
def admin_customer_new(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    form = parse_post(environ)
    lat, lng, err = _parse_latlng(form)
    if err:
        raise HttpError(400, err)
    device_quota = _parse_device_quota(form)
    cur = conn.execute(
        "INSERT INTO Customers (name, phone, email, line_id, address, tax_id, latitude, longitude, device_quota) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (form.get("name", ""), form.get("phone", ""), form.get("email", ""),
         form.get("line_id", ""), form.get("address", ""), form.get("tax_id", "").strip() or None,
         lat, lng, device_quota),
    )
    customer_id = cur.lastrowid
    conn.commit()
    _sync_customer_to_odoo(conn, customer_id)
    raise Redirect("/admin/customers")


@route("POST", r"/admin/customers/(\d+)/edit")
def admin_customer_edit(environ, m, conn, user):
    require_login(user, "admin", "manager")
    customer_id = int(m.group(1))
    form = parse_post(environ)
    name = form.get("name", "").strip()
    if not name:
        raise Redirect("/admin/customers")
    lat, lng, err = _parse_latlng(form)
    if err:
        raise HttpError(400, err)
    existing = conn.execute("SELECT device_quota FROM Customers WHERE customer_id=?", (customer_id,)).fetchone()
    device_quota = _parse_device_quota(form, default=existing["device_quota"] if existing else None)
    conn.execute(
        """UPDATE Customers SET name=?, phone=?, email=?, line_id=?, address=?, tax_id=?, latitude=?, longitude=?,
           device_quota=? WHERE customer_id=?""",
        (name, form.get("phone", ""), form.get("email", ""), form.get("line_id", ""),
         form.get("address", ""), form.get("tax_id", "").strip() or None, lat, lng, device_quota, customer_id),
    )
    conn.commit()
    _sync_customer_to_odoo(conn, customer_id)
    raise Redirect("/admin/customers")


def _delete_customer_cascade(conn, customer_id):
    """ลบลูกค้า 1 คนพร้อมข้อมูลที่ผูกกันทั้งหมด — ใช้สำหรับกรณีมีรายชื่อซ้ำ (สมัครซ้ำ/แอดมินเพิ่มซ้ำ)
    ลำดับการลบ (ต้องเรียงตาม FK เอง เพราะ schema ไม่มี ON DELETE CASCADE):
      1. เครื่องพิมพ์ทุกเครื่องของลูกค้า (cascade ลบตั๋วซ่อม/ใบเสนอราคา/ประวัติซ่อม/ไฟล์แนบไปด้วย ผ่าน
         _delete_device_cascade เดียวกับตอนแอดมินลบเครื่องพิมพ์ทีละเครื่อง)
      2. บัญชี login ที่ผูกกับลูกค้าคนนี้ (Users.customer_id) ถ้ามี — ลบทิ้งไปด้วย เพราะ login ที่ชี้ไป
         ลูกค้าที่ไม่มีอยู่แล้วจะใช้งานไม่ได้อยู่ดี (พร้อมลบการแจ้งเตือนของบัญชีนั้น)
      3. ยอดขาย (Sales_Orders) ที่เคยผูกกับลูกค้าคนนี้ — "ไม่ลบ" แต่ตัดการผูก (SET customer_id=NULL)
         เพื่อรักษาประวัติการขาย/ยอดขายไว้ครบ (Sales_Orders.customer_id ออกแบบให้ไม่บังคับกรอกอยู่แล้ว)
      4. ลบแถวลูกค้าเอง

    หมายเหตุ: ถ้าเคยซิงก์ไป Odoo ไว้แล้ว (odoo_partner_id) จะ "ไม่ลบ" res.partner ฝั่ง Odoo ตามไปด้วย
    (การซิงก์เป็นแบบทางเดียว ไป Odoo อย่างเดียว ไม่มีกลไกลบย้อนกลับ) ถ้าต้องการลบฝั่ง Odoo ด้วย ต้องเข้าไป
    ลบเองที่ Odoo โดยตรง"""
    for row in conn.execute("SELECT device_sn FROM Devices WHERE customer_id=?", (customer_id,)).fetchall():
        _delete_device_cascade(conn, row["device_sn"])

    for row in conn.execute("SELECT user_id FROM Users WHERE customer_id=?", (customer_id,)).fetchall():
        conn.execute("DELETE FROM Notifications WHERE user_id=?", (row["user_id"],))
        conn.execute("DELETE FROM Users WHERE user_id=?", (row["user_id"],))

    conn.execute("UPDATE Sales_Orders SET customer_id=NULL WHERE customer_id=?", (customer_id,))
    conn.execute("DELETE FROM Customers WHERE customer_id=?", (customer_id,))


@route("POST", r"/admin/customers/(\d+)/delete")
def admin_customer_delete(environ, m, conn, user):
    """ลบลูกค้า 1 คนถาวร — เฉพาะแอดมินเท่านั้น (ต่างจากแก้ไขข้อมูลลูกค้าที่ผู้จัดการทำได้ด้วย) เพราะเป็น
    การลบข้อมูลถาวรที่กู้คืนไม่ได้ ใช้สำหรับล้างรายชื่อลูกค้าที่สร้างซ้ำโดยไม่ได้ตั้งใจ"""
    require_login(user, "admin")
    customer_id = int(m.group(1))
    existing = conn.execute("SELECT customer_id FROM Customers WHERE customer_id=?", (customer_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบลูกค้ารายนี้")
    _delete_customer_cascade(conn, customer_id)
    conn.commit()
    raise Redirect("/admin/customers")


DEVICE_STATUSES = ["Active", "Decommissioned", "Sold"]
DEVICE_STATUS_LABELS = {"Active": "ใช้งานอยู่", "Decommissioned": "เลิกใช้แล้ว", "Sold": "ขายต่อแล้ว"}


@route("POST", r"/admin/devices/new")
def admin_device_new(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    form = parse_post(environ)
    status = form.get("status") if form.get("status") in DEVICE_STATUSES else "Active"
    conn.execute(
        """INSERT INTO Devices (device_sn, customer_id, model, type, purchase_date, warranty_end_date, status, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (form.get("device_sn", ""), form.get("customer_id", ""), form.get("model", ""),
         form.get("type", "FDM"), form.get("purchase_date", ""), form.get("warranty_end_date", ""), status, db.now()),
    )
    conn.commit()
    raise Redirect("/admin/customers")


def _delete_ticket_cascade(conn, ticket_id):
    """ลบตั๋วซ่อม 1 ใบพร้อมข้อมูลที่ผูกกันทั้งหมด (ใบเสนอราคา+รายการย่อย, ประวัติซ่อม,
    ไฟล์แนบ) — ต้องลบเรียงตามลำดับ FK เอง เพราะ schema ไม่มี ON DELETE CASCADE
    หมายเหตุ: ไม่คืนสต็อกอะไหล่ที่เคยเบิกไปแล้ว เพราะถือว่าอะไหล่ถูกใช้จริงกับเครื่องลูกค้าไปแล้ว"""
    quote_ids = [r["quote_id"] for r in conn.execute(
        "SELECT quote_id FROM Quotations WHERE ticket_id=?", (ticket_id,)
    ).fetchall()]
    for qid in quote_ids:
        conn.execute("DELETE FROM Quotation_Items WHERE quote_id=?", (qid,))
    conn.execute("DELETE FROM Quotations WHERE ticket_id=?", (ticket_id,))
    conn.execute("DELETE FROM Service_Logs WHERE ticket_id=?", (ticket_id,))
    media = conn.execute("SELECT * FROM Ticket_Media WHERE ticket_id=?", (ticket_id,)).fetchall()
    for md in media:
        try:
            os.remove(os.path.join(UPLOADS_DIR, str(ticket_id), md["stored_name"]))
        except OSError:
            pass
    conn.execute("DELETE FROM Ticket_Media WHERE ticket_id=?", (ticket_id,))
    conn.execute("DELETE FROM Tickets WHERE ticket_id=?", (ticket_id,))


@route("POST", r"/admin/devices/(.+)/edit")
def admin_device_edit(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    form = parse_post(environ)
    model = form.get("model", "").strip()
    if not model:
        raise Redirect("/admin/customers")
    # ปล่อยว่าง = ไม่เปลี่ยนหมายเลขเครื่อง (SN เดิม)
    new_sn = form.get("device_sn", "").strip() or sn
    status = form.get("status") if form.get("status") in DEVICE_STATUSES else device["status"]

    if new_sn != sn:
        dup = conn.execute("SELECT 1 FROM Devices WHERE device_sn=?", (new_sn,)).fetchone()
        if dup:
            raise HttpError(400, f"หมายเลขเครื่อง (SN) '{new_sn}' มีอยู่ในระบบแล้ว กรุณาใช้หมายเลขอื่น")
        # เปลี่ยน primary key ของเครื่อง (device_sn) — schema ไม่มี ON UPDATE CASCADE บน FK ของ
        # Tickets/Maintenance_Logs/Print_Sessions/Notifications และ Postgres ตรวจ FK ทันทีทุกคำสั่ง
        # (ไม่มี SET FOREIGN_KEY_CHECKS แบบ MySQL ให้ปิดชั่วคราว) จึงต้อง: (1) สร้างแถวเครื่องใหม่ด้วย SN ใหม่ก่อน
        # (2) ย้ายทุกตารางลูกให้ชี้ไปแถวใหม่ (3) ค่อยลบแถวเดิม — ไม่มีจังหวะไหนที่ FK ชี้ไปแถวที่ไม่มีอยู่จริงเลย
        conn.execute(
            """INSERT INTO Devices (device_sn, customer_id, model, type, purchase_date, warranty_end_date,
                                     status, created_at, total_usage_hours, purchase_proof_filename)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (new_sn, device["customer_id"], model, form.get("type", "FDM"), form.get("purchase_date") or None,
             form.get("warranty_end_date") or None, status, device["created_at"], device["total_usage_hours"],
             device["purchase_proof_filename"]),
        )
        conn.execute("UPDATE Tickets SET device_sn=? WHERE device_sn=?", (new_sn, sn))
        conn.execute("UPDATE Maintenance_Logs SET device_sn=? WHERE device_sn=?", (new_sn, sn))
        conn.execute("UPDATE Print_Sessions SET device_sn=? WHERE device_sn=?", (new_sn, sn))
        conn.execute("UPDATE Notifications SET device_sn=? WHERE device_sn=?", (new_sn, sn))
        conn.execute("DELETE FROM Devices WHERE device_sn=?", (sn,))
    else:
        conn.execute(
            "UPDATE Devices SET model=?, type=?, purchase_date=?, warranty_end_date=?, status=? WHERE device_sn=?",
            (model, form.get("type", "FDM"), form.get("purchase_date") or None,
             form.get("warranty_end_date") or None, status, sn),
        )
    conn.commit()
    raise Redirect("/admin/customers")


@route("POST", r"/admin/devices/(.+)/maintenance")
def admin_device_maintenance_log(environ, m, conn, user):
    """บันทึกแบบย่อว่าช่างเข้าบำรุงรักษาเครื่องนี้แล้ว (จากหน้ารายการลูกค้า/เครื่อง) — บันทึกอิสระ
    ไม่ผูกกับแผนงานเฉพาะ (plan_item_id เป็น NULL) สำหรับบันทึกละเอียดแบบเลือกงานตามแผนได้ ให้ใช้
    หน้า /device/<sn>/maintenance/log แทน ซึ่งลูกค้าเองก็ใช้บันทึกได้เช่นกัน"""
    require_login(user, "admin", "manager")
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    form = parse_post(environ)
    performed_at = form.get("performed_at") or db.now()[:10]
    conn.execute(
        "INSERT INTO Maintenance_Logs (device_sn, performed_at, notes, performed_by) VALUES (?,?,?,?)",
        (sn, performed_at, form.get("notes", ""), user["user_id"]),
    )
    conn.commit()
    raise Redirect("/admin/customers")


def _delete_device_cascade(conn, sn):
    """ลบเครื่องพิมพ์ 1 เครื่องพร้อมข้อมูลที่ผูกกันทั้งหมด (ตั๋วซ่อม/ใบเสนอราคา/ประวัติซ่อม/ไฟล์แนบ ผ่าน
    _delete_ticket_cascade, การแจ้งเตือน, session พิมพ์, ประวัติบำรุงรักษา) — แยกเป็นฟังก์ชันกลาง เพราะใช้
    ทั้งตอนแอดมินลบเครื่องทีละเครื่อง (admin_device_delete) และตอนลบลูกค้าทั้งคน (_delete_customer_cascade
    ซึ่งต้องลบทุกเครื่องของลูกค้าคนนั้นไปด้วย)"""
    ticket_ids = [r["ticket_id"] for r in conn.execute(
        "SELECT ticket_id FROM Tickets WHERE device_sn=?", (sn,)
    ).fetchall()]
    for tid in ticket_ids:
        _delete_ticket_cascade(conn, tid)
    conn.execute("DELETE FROM Notifications WHERE device_sn=?", (sn,))
    conn.execute("DELETE FROM Print_Sessions WHERE device_sn=?", (sn,))
    conn.execute("DELETE FROM Maintenance_Logs WHERE device_sn=?", (sn,))
    conn.execute("DELETE FROM Devices WHERE device_sn=?", (sn,))


@route("POST", r"/admin/devices/(.+)/delete")
def admin_device_delete(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sn = m.group(1)
    device = conn.execute("SELECT * FROM Devices WHERE device_sn=?", (sn,)).fetchone()
    if not device:
        raise HttpError(404, "ไม่พบเครื่องพิมพ์นี้")
    _delete_device_cascade(conn, sn)
    conn.commit()
    raise Redirect("/admin/customers")


PRODUCT_CATEGORIES = ["FDM_Printer", "Resin_Printer", "Spare_Part", "Material", "Other"]
PRODUCT_CATEGORY_LABELS = {
    "FDM_Printer": "เครื่องพิมพ์ FDM",
    "Resin_Printer": "เครื่องพิมพ์ Resin",
    "Spare_Part": "อะไหล่",
    "Material": "วัสดุพิมพ์",
    "Other": "อื่นๆ",
}
PRODUCT_CATEGORY_ICONS = {
    "FDM_Printer": "🖨️",
    "Resin_Printer": "🧪",
    "Spare_Part": "🔧",
    "Material": "🧵",
    "Other": "📦",
}
PRODUCT_CATEGORY_COLORS = {
    "FDM_Printer": "#3f7fe0",
    "Resin_Printer": "#6c4fd6",
    "Spare_Part": "#22c9e6",
    "Material": "#f1c40f",
    "Other": "#8a94a6",
}


def _load_parts(conn, q=None, center_id=None):
    """ดึงรายการสินค้าในคลัง — ค้นหาได้จาก SKU / ชื่อสินค้า / รุ่นที่ใช้ร่วมกันได้
    center_id: ถ้าไม่ใช่ None จะกรองเฉพาะสินค้าของศูนย์นั้น + สินค้าคลังกลาง (center_id IS NULL)
    — ใช้จำกัดสิทธิ์ manager ให้เห็นเฉพาะสินค้าศูนย์ตัวเอง"""
    conditions, params = [], []
    if center_id is not None:
        conditions.append("(center_id = ? OR center_id IS NULL)")
        params.append(center_id)
    if q:
        like = f"%{q}%"
        # ILIKE แทน LIKE — Postgres LIKE ตัวพิมพ์เล็ก/ใหญ่ต่างกันโดย default ต่างจาก MySQL ที่ใช้
        # collation utf8mb4_unicode_ci (ไม่สนตัวพิมพ์เล็ก/ใหญ่) ใช้ ILIKE เพื่อคงพฤติกรรมค้นหาเดิม
        conditions.append("(part_sku ILIKE ? OR part_name ILIKE ? OR compatible_models ILIKE ?)")
        params.extend([like, like, like])
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return conn.execute(f"SELECT * FROM Spare_Parts {where} ORDER BY part_sku", tuple(params)).fetchall()


def _load_part_images_map(conn, skus):
    """ดึงรูปแกลเลอรี (Part_Images) ของสินค้าหลาย SKU พร้อมกันในคิวรีเดียว (กัน N+1 query)
    คืน dict: part_sku -> list ของ {image_id, stored_name} เรียงตามลำดับที่อัปโหลด"""
    skus = list(skus)
    if not skus:
        return {}
    placeholders = ",".join(["?"] * len(skus))
    rows = conn.execute(
        f"SELECT image_id, part_sku, stored_name FROM Part_Images WHERE part_sku IN ({placeholders}) ORDER BY image_id",
        tuple(skus),
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["part_sku"], []).append({"image_id": r["image_id"], "stored_name": r["stored_name"]})
    return out


def _inventory_ctx(conn, user, q=""):
    """context กลางสำหรับ render admin_inventory.html — ใช้ร่วมกันทุก route เพื่อไม่ต้องพิมพ์ซ้ำ
    ถ้าเป็น manager จะกรองสินค้า+ตัวเลือกศูนย์บริการให้เห็นเฉพาะศูนย์ตัวเองเท่านั้น"""
    is_manager = user["role"] == "manager"
    scope_center = user.get("center_id") if is_manager else None

    if is_manager and not scope_center:
        # manager ยังไม่ได้ถูกผูกกับศูนย์บริการใด — ไม่แสดงสินค้าใดๆ จนกว่าแอดมินจะกำหนดศูนย์ให้
        return {"parts": [], "centers": [], "q": q,
                "threshold": db.HIGH_COST_APPROVAL_THRESHOLD, "max_image_mb": MAX_PART_IMAGE_MB,
                "max_images": MAX_PART_IMAGES,
                "categories": PRODUCT_CATEGORIES, "category_labels": PRODUCT_CATEGORY_LABELS,
                "category_icons": PRODUCT_CATEGORY_ICONS, "parts_for_js": [], "shelves": []}

    centers_all = conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall()
    centers = [c for c in centers_all if c["center_id"] == scope_center] if is_manager else centers_all
    parts_raw = _load_parts(conn, q, center_id=scope_center if is_manager else None)
    images_map = _load_part_images_map(conn, (p["part_sku"] for p in parts_raw))
    parts = []
    for p in parts_raw:
        gallery = images_map.get(p["part_sku"], [])
        # จำนวนรูปทั้งหมดของสินค้าชิ้นนี้ = รูปปกหลัก (ถ้ามี) + รูปแกลเลอรี — ใช้เช็คว่ายังอัปโหลดเพิ่มได้อีกกี่รูป
        total_images = (1 if p["image_filename"] else 0) + len(gallery)
        parts.append(dict(p, gallery=gallery, gallery_slots_left=max(0, MAX_PART_IMAGES - total_images)))

    # ข้อมูลสำหรับ popup "รายละเอียดสินค้า" ที่คลิกจากรูปในตาราง (ดูอย่างเดียว แยกจากฟอร์มแก้ไข)
    center_name_by_id = {c["center_id"]: c["name"] for c in centers_all}
    parts_for_js = [
        {
            "sku": p["part_sku"], "name": p["part_name"],
            "category": p["category"],
            "category_label": PRODUCT_CATEGORY_LABELS.get(p["category"], p["category"]),
            "category_icon": PRODUCT_CATEGORY_ICONS.get(p["category"], "📦"),
            "description": p["description"] or "",
            "compatible_models": p["compatible_models"] or "",
            "stock_quantity": p["stock_quantity"], "reorder_level": p["reorder_level"],
            "cost_price": p["cost_price"], "labor_fee": p["labor_fee"], "commission_fee": p["commission_fee"],
            "ownership": p["ownership"],
            "center_name": center_name_by_id.get(p["center_id"]),
            "storage_location": p["storage_location"] or "",
            "images": ([p["image_filename"]] if p["image_filename"] else []) + [g["stored_name"] for g in p["gallery"]],
        }
        for p in parts
    ]
    # กลุ่มสินค้าตามตำแหน่งจัดเก็บ (ชั้นวาง) — ใช้แสดงเป็น visualize ชั้นวางแบบคลิกกรองได้ที่หน้าคลังสินค้า
    # เฉพาะสินค้าที่กรอก "ตำแหน่งจัดเก็บสินค้า" ไว้เท่านั้นที่จะถูกจัดกลุ่ม (สินค้าที่ยังไม่ระบุตำแหน่งจะไม่ขึ้นเป็นชั้น)
    shelf_counts = Counter(p["storage_location"] for p in parts if p["storage_location"])
    shelves = [{"location": loc, "count": cnt} for loc, cnt in sorted(shelf_counts.items())]
    return {
        "parts": parts,
        "centers": centers,
        "q": q,
        "threshold": db.HIGH_COST_APPROVAL_THRESHOLD,
        "max_image_mb": MAX_PART_IMAGE_MB,
        "max_images": MAX_PART_IMAGES,
        "categories": PRODUCT_CATEGORIES,
        "category_labels": PRODUCT_CATEGORY_LABELS,
        "category_icons": PRODUCT_CATEGORY_ICONS,
        "parts_for_js": parts_for_js,
        "shelves": shelves,
    }


@route("GET", r"/admin/inventory")
def admin_inventory(environ, m, conn, user):
    require_login(user, "admin", "manager")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    q = qs.get("q", [""])[0].strip()
    return render("admin_inventory.html", user=user, error=None, **_inventory_ctx(conn, user, q))


@route("POST", r"/admin/inventory/(.+)/restock")
def admin_inventory_restock(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku = m.group(1)
    part = conn.execute("SELECT center_id FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบสินค้านี้")
    require_center_access(user, part["center_id"])
    form = parse_post(environ)
    qty = int(form.get("qty", 0) or 0)
    conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?", (qty, sku))
    conn.commit()
    raise Redirect("/admin/inventory")


def save_part_image(sku, file_info):
    """ตรวจสอบและบันทึกรูปอะไหล่ 1 ไฟล์ คืนชื่อไฟล์ที่บันทึกจริง หรือ None ถ้าไม่ได้แนบไฟล์มา"""
    if not file_info or not file_info.get("filename"):
        return None
    if not file_info["content_type"].startswith("image/"):
        raise ValueError(f"ไฟล์ '{file_info['filename']}' ไม่ใช่ไฟล์รูปภาพที่รองรับ")
    if len(file_info["data"]) > MAX_PART_IMAGE_BYTES:
        size_mb = round(len(file_info["data"]) / (1024 * 1024), 1)
        raise ValueError(f"ไฟล์รูปขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_PART_IMAGE_MB} MB)")
    os.makedirs(PART_IMAGES_DIR, exist_ok=True)
    stored = f"{safe_filename(sku)}_{uuid.uuid4().hex[:8]}_{safe_filename(file_info['filename'])}"
    with open(os.path.join(PART_IMAGES_DIR, stored), "wb") as out:
        out.write(file_info["data"])
    return stored


@route("POST", r"/admin/inventory/new")
def admin_inventory_new(environ, m, conn, user):
    require_login(user, "admin", "manager")
    fields, files = parse_multipart(environ)
    sku = fields.get("part_sku", "").strip()
    name = fields.get("part_name", "").strip()

    def with_error(msg):
        return render("admin_inventory.html", user=user, error=msg, **_inventory_ctx(conn, user))

    if not sku or not name:
        return with_error("กรุณากรอกรหัสสินค้า (SKU) และชื่อสินค้า")
    try:
        stock = int(fields.get("stock_quantity") or 0)
        cost = float(fields.get("cost_price") or 0)
        labor = float(fields.get("labor_fee") or 0)
        commission = float(fields.get("commission_fee") or 0)
        reorder = int(fields.get("reorder_level") or 0)
    except ValueError:
        return with_error("จำนวน/ราคา ต้องเป็นตัวเลข")

    center_id = fields.get("center_id") or None
    if center_id:
        center_ok = conn.execute("SELECT 1 FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
        if not center_ok:
            return with_error("ศูนย์บริการที่เลือกไม่ถูกต้อง")
    if user["role"] == "manager" and center_id and int(center_id) != user.get("center_id"):
        return with_error("คุณกำหนดศูนย์บริการอื่นให้สินค้าไม่ได้ เลือกได้เฉพาะศูนย์ของตัวเองหรือคลังกลาง")

    category = fields.get("category") if fields.get("category") in PRODUCT_CATEGORIES else "Spare_Part"
    ownership = "consignment" if fields.get("ownership") == "consignment" else "owned"

    image_file = (files.get("image") or [None])[0]
    try:
        image_filename = save_part_image(sku, image_file)
    except ValueError as e:
        return with_error(str(e))

    try:
        conn.execute(
            """INSERT INTO Spare_Parts (part_sku, part_name, compatible_models, stock_quantity,
                                         cost_price, labor_fee, commission_fee, reorder_level,
                                         center_id, image_filename, category, description, ownership,
                                         storage_location)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sku, name, fields.get("compatible_models", ""), stock, cost, labor, commission,
             reorder, center_id, image_filename, category, fields.get("description", "").strip() or None, ownership,
             fields.get("storage_location", "").strip() or None),
        )
        conn.commit()
    except db.IntegrityError:
        return with_error(f"รหัสสินค้า (SKU) '{sku}' มีอยู่แล้วในระบบ")
    _sync_product_to_odoo(conn, sku)
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/edit")
def admin_inventory_edit(environ, m, conn, user):
    """แก้ไขข้อมูลสินค้า — รวมทุกอย่างไว้ในฟอร์มเดียว (multipart) รวมถึงเปลี่ยนรูปหลักได้ในหน้าเดียวกัน
    ไม่ต้องแยกไปอัปโหลดรูปที่ฟอร์มอื่นเหมือนเดิม เพื่อให้แก้ไขสินค้าได้ง่ายและรวดเร็วขึ้น"""
    require_login(user, "admin", "manager")
    sku = m.group(1)
    fields, files = parse_multipart(environ)

    def with_error(msg):
        return render("admin_inventory.html", user=user, error=msg, **_inventory_ctx(conn, user))

    part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบสินค้านี้")
    require_center_access(user, part["center_id"])

    name = fields.get("part_name", "").strip()
    if not name:
        return with_error("กรุณากรอกชื่อสินค้า")
    try:
        stock = int(fields.get("stock_quantity") or 0)
        cost = float(fields.get("cost_price") or 0)
        labor = float(fields.get("labor_fee") or 0)
        commission = float(fields.get("commission_fee") or 0)
        reorder = int(fields.get("reorder_level") or 0)
    except ValueError:
        return with_error("จำนวน/ราคา ต้องเป็นตัวเลข")

    center_id = fields.get("center_id") or None
    if center_id:
        center_ok = conn.execute("SELECT 1 FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
        if not center_ok:
            return with_error("ศูนย์บริการที่เลือกไม่ถูกต้อง")
    if user["role"] == "manager" and center_id and int(center_id) != user.get("center_id"):
        return with_error("คุณกำหนดศูนย์บริการอื่นให้สินค้าไม่ได้ เลือกได้เฉพาะศูนย์ของตัวเองหรือคลังกลาง")

    category = fields.get("category") if fields.get("category") in PRODUCT_CATEGORIES else part["category"]
    ownership = "consignment" if fields.get("ownership") == "consignment" else "owned"

    image_file = (files.get("image") or [None])[0]
    try:
        new_image_filename = save_part_image(sku, image_file)
    except ValueError as e:
        return with_error(str(e))
    image_filename = new_image_filename or part["image_filename"]

    # เปลี่ยนรหัสสินค้า (SKU) ได้ — ปล่อยว่าง = ไม่เปลี่ยน (SKU เดิม)
    new_sku = fields.get("part_sku", "").strip() or sku
    if new_sku != sku:
        dup = conn.execute("SELECT 1 FROM Spare_Parts WHERE part_sku=?", (new_sku,)).fetchone()
        if dup:
            return with_error(f"รหัสสินค้า (SKU) '{new_sku}' มีอยู่ในระบบแล้ว กรุณาใช้รหัสอื่น")

    if new_sku == sku:
        conn.execute(
            """UPDATE Spare_Parts SET part_name=?, compatible_models=?, stock_quantity=?, cost_price=?, labor_fee=?,
                                       commission_fee=?, reorder_level=?, center_id=?, category=?, description=?,
                                       image_filename=?, ownership=?, storage_location=?
               WHERE part_sku=?""",
            (name, fields.get("compatible_models", ""), stock, cost, labor, commission, reorder, center_id, category,
             fields.get("description", "").strip() or None, image_filename, ownership,
             fields.get("storage_location", "").strip() or None, sku),
        )
    else:
        # part_sku เป็น primary key ที่ตารางอื่น (Part_Images, Service_Logs, Sale_Items, Restock_Order_Items)
        # อ้างอิงผ่าน FOREIGN KEY โดยไม่มี ON UPDATE CASCADE — Postgres ตรวจ FK ทันทีทุกคำสั่ง (ไม่ใช่ตอน commit
        # เหมือน MySQL ที่ปิดด้วย SET FOREIGN_KEY_CHECKS ได้) จึงต้อง: (1) สร้างแถวสินค้าใหม่ด้วย SKU ใหม่ก่อน
        # (2) ย้ายทุกตารางลูกให้ชี้ไปแถวใหม่ (3) ค่อยลบแถวเดิม — ไม่มีจังหวะไหนที่ FK ชี้ไปแถวที่ไม่มีอยู่จริงเลย
        conn.execute(
            """INSERT INTO Spare_Parts (part_sku, part_name, compatible_models, stock_quantity, cost_price,
                                         labor_fee, commission_fee, center_id, reorder_level, image_filename,
                                         category, description, ownership, odoo_product_id, storage_location)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (new_sku, name, fields.get("compatible_models", ""), stock, cost, labor, commission, center_id, reorder,
             image_filename, category, fields.get("description", "").strip() or None, ownership,
             part["odoo_product_id"], fields.get("storage_location", "").strip() or None),
        )
        conn.execute("UPDATE Part_Images SET part_sku=? WHERE part_sku=?", (new_sku, sku))
        conn.execute("UPDATE Service_Logs SET part_sku_used=? WHERE part_sku_used=?", (new_sku, sku))
        conn.execute("UPDATE Sale_Items SET part_sku=? WHERE part_sku=?", (new_sku, sku))
        conn.execute("UPDATE Restock_Order_Items SET part_sku=? WHERE part_sku=?", (new_sku, sku))
        conn.execute("DELETE FROM Spare_Parts WHERE part_sku=?", (sku,))

    conn.commit()
    _sync_product_to_odoo(conn, new_sku)
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/image")
def admin_inventory_image(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku = m.group(1)
    part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบสินค้านี้")
    require_center_access(user, part["center_id"])

    fields, files = parse_multipart(environ)
    image_file = (files.get("image") or [None])[0]
    try:
        image_filename = save_part_image(sku, image_file)
    except ValueError as e:
        return render("admin_inventory.html", user=user, error=str(e), **_inventory_ctx(conn, user))

    if image_filename:
        conn.execute("UPDATE Spare_Parts SET image_filename=? WHERE part_sku=?", (image_filename, sku))
        conn.commit()
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/gallery")
def admin_inventory_gallery_upload(environ, m, conn, user):
    """อัปโหลดรูปเพิ่มเข้าแกลเลอรีสินค้า (นอกเหนือจากรูปปกหลัก) — รวมกันได้สูงสุด MAX_PART_IMAGES รูปต่อสินค้า
    อัปโหลดพร้อมกันหลายไฟล์ได้ในครั้งเดียว (input file แบบ multiple) แต่ถ้าเกินโควตาที่เหลือจะรับแค่เท่าที่พอ"""
    require_login(user, "admin", "manager")
    sku = m.group(1)
    part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบสินค้านี้")
    require_center_access(user, part["center_id"])

    fields, files = parse_multipart(environ)
    new_files = files.get("images") or []

    existing_count = conn.execute(
        "SELECT COUNT(*) AS n FROM Part_Images WHERE part_sku=?", (sku,)
    ).fetchone()["n"]
    total_now = (1 if part["image_filename"] else 0) + existing_count
    slots_left = max(0, MAX_PART_IMAGES - total_now)

    if slots_left <= 0:
        return render("admin_inventory.html", user=user,
                       error=f"สินค้า '{sku}' มีรูปครบ {MAX_PART_IMAGES} รูปแล้ว กรุณาลบรูปเดิมก่อนเพิ่มรูปใหม่",
                       **_inventory_ctx(conn, user))

    try:
        for file_info in new_files[:slots_left]:
            stored = save_part_image(sku, file_info)
            if stored:
                conn.execute(
                    "INSERT INTO Part_Images (part_sku, stored_name, uploaded_at) VALUES (?,?,?)",
                    (sku, stored, db.now()),
                )
        conn.commit()
    except ValueError as e:
        return render("admin_inventory.html", user=user, error=str(e), **_inventory_ctx(conn, user))

    if len(new_files) > slots_left:
        return render("admin_inventory.html", user=user,
                       error=f"อัปโหลดได้แค่ {slots_left} จาก {len(new_files)} รูปที่เลือก "
                             f"(สินค้า '{sku}' มีรูปได้สูงสุด {MAX_PART_IMAGES} รูป) — รูปที่เหลือไม่ได้ถูกเพิ่ม",
                       **_inventory_ctx(conn, user))
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/gallery/(\d+)/delete")
def admin_inventory_gallery_delete(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku, image_id = m.group(1), int(m.group(2))
    part = conn.execute("SELECT center_id FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบสินค้านี้")
    require_center_access(user, part["center_id"])

    img = conn.execute(
        "SELECT * FROM Part_Images WHERE image_id=? AND part_sku=?", (image_id, sku)
    ).fetchone()
    if img:
        try:
            os.remove(os.path.join(PART_IMAGES_DIR, img["stored_name"]))
        except OSError:
            pass
        conn.execute("DELETE FROM Part_Images WHERE image_id=?", (image_id,))
        conn.commit()
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/delete")
def admin_inventory_delete(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku = m.group(1)
    part = conn.execute("SELECT center_id FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบสินค้านี้")
    require_center_access(user, part["center_id"])
    gallery_imgs = conn.execute("SELECT stored_name FROM Part_Images WHERE part_sku=?", (sku,)).fetchall()
    try:
        conn.execute("DELETE FROM Part_Images WHERE part_sku=?", (sku,))
        conn.execute("DELETE FROM Spare_Parts WHERE part_sku=?", (sku,))
        conn.commit()
    except db.IntegrityError:
        conn.rollback()
        return render("admin_inventory.html", user=user,
                       error=f"ลบ '{sku}' ไม่ได้ เนื่องจากมีประวัติการเบิกใช้สินค้านี้อยู่ในระบบซ่อม",
                       **_inventory_ctx(conn, user))
    for img in gallery_imgs:
        try:
            os.remove(os.path.join(PART_IMAGES_DIR, img["stored_name"]))
        except OSError:
            pass
    raise Redirect("/admin/inventory")


# ------------------------------------------------------- ขั้นตอนการทำงานพาร์ตเนอร์ TDPrinter --
# ขั้นที่ 4 "สั่งซื้อ/ติดตามสถานะ": ศูนย์บริการ (manager) เป็นผู้เริ่มสั่งซื้อสินค้า/อะไหล่เพิ่มจาก HQ (admin)
# -> HQ รับเรื่อง/ดำเนินการ -> HQ ยืนยันจัดส่ง+เลขติดตามพัสดุ -> ศูนย์บริการติดตามและกดยืนยันรับของ
# (กดรับของ = เพิ่มสต็อกให้อัตโนมัติ ไม่รองรับรับของบางส่วน เพื่อให้ workflow เรียบง่ายและทดสอบได้ตรงไปตรงมา)

RESTOCK_STATUS_LABELS = {
    "requested": "🕓 รอ HQ ดำเนินการ",
    "processing": "📦 HQ กำลังเตรียมจัดส่ง",
    "shipped": "🚚 จัดส่งแล้ว (ระหว่างทาง)",
    "received": "✅ ได้รับของแล้ว",
    "cancelled": "❌ ยกเลิก",
}


def _restock_orders_with_items(conn, where_sql="", params=()):
    """โหลดรายการคำสั่งซื้อ (Restock_Orders) พร้อมรายการสินค้าย่อยของแต่ละคำสั่ง — ใช้ร่วมกันทั้งหน้า
    ศูนย์บริการ (เห็นเฉพาะของตัวเอง) และหน้า HQ (เห็นทุกศูนย์)"""
    orders = conn.execute(
        f"""SELECT ro.*, sc.name AS center_name, u.name AS requested_by_name
            FROM Restock_Orders ro
            JOIN Service_Centers sc ON sc.center_id = ro.center_id
            JOIN Users u ON u.user_id = ro.requested_by
            {where_sql}
            ORDER BY (ro.status='requested') DESC, ro.created_at DESC""",
        params,
    ).fetchall()
    result = []
    for o in orders:
        items = conn.execute(
            """SELECT roi.*, sp.part_name FROM Restock_Order_Items roi
               JOIN Spare_Parts sp ON sp.part_sku = roi.part_sku
               WHERE roi.order_id=? ORDER BY roi.item_id""",
            (o["order_id"],),
        ).fetchall()
        result.append(dict(o, order_items=items, status_label=RESTOCK_STATUS_LABELS.get(o["status"], o["status"])))
    return result


@route("GET", r"/manager/restock-orders")
def manager_restock_orders(environ, m, conn, user):
    require_login(user, "manager")
    center_id = user.get("center_id")
    if not center_id:
        raise HttpError(403, "บัญชีนี้ยังไม่ได้ถูกกำหนดศูนย์บริการ")
    parts = _load_parts(conn, center_id=center_id)
    orders = _restock_orders_with_items(conn, "WHERE ro.center_id=?", (center_id,))
    return render("manager_restock_orders.html", user=user, parts=parts, parts_for_js=_parts_for_js(parts),
                  orders=orders, restock_status_labels=RESTOCK_STATUS_LABELS, error=None)


@route("POST", r"/manager/restock-orders/new")
def manager_restock_order_new(environ, m, conn, user):
    require_login(user, "manager")
    center_id = user.get("center_id")
    if not center_id:
        raise HttpError(403, "บัญชีนี้ยังไม่ได้ถูกกำหนดศูนย์บริการ")
    form = parse_post(environ)
    parts = _load_parts(conn, center_id=center_id)
    parts_by_sku = {p["part_sku"]: p for p in parts}

    def with_error(msg):
        orders = _restock_orders_with_items(conn, "WHERE ro.center_id=?", (center_id,))
        return render("manager_restock_orders.html", user=user, parts=parts, parts_for_js=_parts_for_js(parts),
                      orders=orders, restock_status_labels=RESTOCK_STATUS_LABELS, error=msg)

    # ฟอร์มส่งมาเป็นรายบรรทัด (เพิ่ม/ลบบรรทัดได้อิสระฝั่ง JS) — คีย์คือ sku_<idx>, qty_<idx> เหมือนฟอร์มบันทึกการขาย
    line_indexes = sorted({
        key.split("_", 1)[1] for key in form if key.startswith("sku_") and form.get(key)
    })
    line_items = []
    for idx in line_indexes:
        sku = (form.get(f"sku_{idx}") or "").strip()
        if not sku:
            continue
        part = parts_by_sku.get(sku)
        if not part:
            return with_error("มีสินค้าที่เลือกไม่ถูกต้อง หรือไม่ได้อยู่ในคลังของศูนย์นี้ กรุณาเลือกจากรายการค้นหาใหม่")
        qty_raw = (form.get(f"qty_{idx}") or "").strip()
        if not qty_raw:
            continue
        try:
            qty = int(float(qty_raw))
        except ValueError:
            return with_error(f"จำนวนของ '{part['part_name']}' ต้องเป็นตัวเลข")
        if qty <= 0:
            continue
        line_items.append((sku, qty))

    if not line_items:
        return with_error("กรุณาเพิ่มอย่างน้อย 1 รายการสินค้า พร้อมระบุจำนวนที่ต้องการสั่งซื้อ")

    cur = conn.execute(
        "INSERT INTO Restock_Orders (center_id, requested_by, status, notes, created_at) VALUES (?,?,'requested',?,?)",
        (center_id, user["user_id"], form.get("notes", "").strip() or None, db.now()),
    )
    order_id = cur.lastrowid
    for sku, qty in line_items:
        conn.execute(
            "INSERT INTO Restock_Order_Items (order_id, part_sku, quantity_requested) VALUES (?,?,?)",
            (order_id, sku, qty),
        )
    conn.commit()
    raise Redirect("/manager/restock-orders")


@route("POST", r"/manager/restock-orders/(\d+)/receive")
def manager_restock_order_receive(environ, m, conn, user):
    """ศูนย์บริการกดยืนยันว่าได้รับของครบแล้ว — ระบบเพิ่มสต็อกให้อัตโนมัติตามจำนวนที่สั่ง (ไม่รองรับรับของบางส่วน)"""
    require_login(user, "manager")
    order_id = int(m.group(1))
    order = conn.execute("SELECT * FROM Restock_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    require_center_access(user, order["center_id"])
    if order["status"] != "shipped":
        raise HttpError(400, "รับของได้เฉพาะคำสั่งซื้อที่ HQ ยืนยันจัดส่งแล้วเท่านั้น")
    items = conn.execute("SELECT * FROM Restock_Order_Items WHERE order_id=?", (order_id,)).fetchall()
    for it in items:
        conn.execute(
            "UPDATE Restock_Order_Items SET quantity_received=? WHERE item_id=?",
            (it["quantity_requested"], it["item_id"]),
        )
        conn.execute(
            "UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
            (it["quantity_requested"], it["part_sku"]),
        )
    conn.execute("UPDATE Restock_Orders SET status='received', received_at=? WHERE order_id=?", (db.now(), order_id))
    conn.commit()
    raise Redirect("/manager/restock-orders")


@route("POST", r"/manager/restock-orders/(\d+)/cancel")
def manager_restock_order_cancel(environ, m, conn, user):
    require_login(user, "manager")
    order_id = int(m.group(1))
    order = conn.execute("SELECT * FROM Restock_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    require_center_access(user, order["center_id"])
    if order["status"] not in ("requested", "processing"):
        raise HttpError(400, "ยกเลิกได้เฉพาะคำสั่งซื้อที่ยังไม่ได้จัดส่งเท่านั้น")
    conn.execute("UPDATE Restock_Orders SET status='cancelled' WHERE order_id=?", (order_id,))
    conn.commit()
    raise Redirect("/manager/restock-orders")


@route("GET", r"/admin/restock-orders")
def admin_restock_orders(environ, m, conn, user):
    require_login(user, "admin")
    orders = _restock_orders_with_items(conn)
    return render("admin_restock_orders.html", user=user, orders=orders, restock_status_labels=RESTOCK_STATUS_LABELS)


@route("POST", r"/admin/restock-orders/(\d+)/process")
def admin_restock_order_process(environ, m, conn, user):
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = conn.execute("SELECT * FROM Restock_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    if order["status"] != "requested":
        raise HttpError(400, "ดำเนินการได้เฉพาะคำสั่งซื้อที่ยังไม่ได้เริ่มดำเนินการเท่านั้น")
    conn.execute("UPDATE Restock_Orders SET status='processing', processed_at=? WHERE order_id=?", (db.now(), order_id))
    conn.commit()
    raise Redirect("/admin/restock-orders")


@route("POST", r"/admin/restock-orders/(\d+)/ship")
def admin_restock_order_ship(environ, m, conn, user):
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = conn.execute("SELECT * FROM Restock_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    if order["status"] not in ("requested", "processing"):
        raise HttpError(400, "ยืนยันจัดส่งได้เฉพาะคำสั่งซื้อที่ยังไม่ได้จัดส่งเท่านั้น")
    form = parse_post(environ)
    tracking = form.get("tracking_number", "").strip()
    conn.execute(
        "UPDATE Restock_Orders SET status='shipped', tracking_number=?, shipped_at=? WHERE order_id=?",
        (tracking or None, db.now(), order_id),
    )
    conn.commit()
    raise Redirect("/admin/restock-orders")


@route("POST", r"/admin/restock-orders/(\d+)/cancel")
def admin_restock_order_cancel(environ, m, conn, user):
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = conn.execute("SELECT * FROM Restock_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    if order["status"] in ("received", "cancelled"):
        raise HttpError(400, "ยกเลิกคำสั่งซื้อนี้ไม่ได้แล้ว")
    conn.execute("UPDATE Restock_Orders SET status='cancelled' WHERE order_id=?", (order_id,))
    conn.commit()
    raise Redirect("/admin/restock-orders")


# ----------------------------------------------- แอดมิน (HQ) สร้าง/แก้ไข/ลบคำสั่งซื้อเอง --
# นอกจากศูนย์บริการ (manager) จะเป็นผู้เริ่มสั่งซื้อได้แล้ว แอดมินก็สร้างคำสั่งซื้อ/จัดส่งสินค้าไปยัง
# ศูนย์บริการใดก็ได้เองโดยตรง (ไม่ต้องรอศูนย์ร้องขอ) พร้อมแก้ไข/ลบคำสั่งซื้อที่มีอยู่ได้ทุกสถานะ —
# ใช้สร้าง "ใบส่งสินค้า" (delivery note) ประกอบการจัดส่งจริงได้ด้วย (ดูฟังก์ชัน admin_restock_delivery_note ด้านล่าง)

def _get_hq_center(conn):
    """คืนศูนย์บริการที่ถูกตั้งเป็น "สำนักงานใหญ่" (is_headquarters=1) — ใช้เป็นข้อมูล "ผู้ส่ง" บนใบส่งสินค้า
    มีได้สาขาเดียวในระบบ (บังคับที่ชั้นแอปตอนติ๊กในหน้าศูนย์บริการ ไม่ใช่ระดับฐานข้อมูล) — คืน None ถ้ายังไม่ได้ตั้งค่า"""
    return conn.execute(
        "SELECT * FROM Service_Centers WHERE is_headquarters=1 ORDER BY center_id LIMIT 1"
    ).fetchone()


def _get_restock_order_or_404(conn, order_id):
    order = conn.execute("SELECT * FROM Restock_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    return order


@route("GET", r"/admin/restock-orders/new")
def admin_restock_order_new_form(environ, m, conn, user):
    require_login(user, "admin")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    center_id_raw = qs.get("center_id", [""])[0].strip()
    centers = conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall()
    center = None
    parts = []
    if center_id_raw.isdigit():
        center = next((c for c in centers if c["center_id"] == int(center_id_raw)), None)
        if center:
            parts = _load_parts(conn, center_id=center["center_id"])
    return render("admin_restock_order_new.html", user=user, centers=centers, center=center,
                  parts=parts, parts_for_js=_parts_for_js_with_category(parts), error=None,
                  category_labels=PRODUCT_CATEGORY_LABELS, category_icons=PRODUCT_CATEGORY_ICONS)


@route("POST", r"/admin/restock-orders/new")
def admin_restock_order_new_submit(environ, m, conn, user):
    require_login(user, "admin")
    form = parse_post(environ)
    center_id_raw = (form.get("center_id") or "").strip()
    if not center_id_raw.isdigit():
        raise HttpError(400, "กรุณาเลือกศูนย์บริการปลายทาง")
    center_id = int(center_id_raw)
    center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
    if not center:
        raise HttpError(404, "ไม่พบศูนย์บริการนี้")

    parts = _load_parts(conn, center_id=center_id)
    parts_by_sku = {p["part_sku"]: p for p in parts}

    def with_error(msg):
        centers = conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall()
        return render("admin_restock_order_new.html", user=user, centers=centers, center=center,
                      parts=parts, parts_for_js=_parts_for_js_with_category(parts), error=msg,
                      category_labels=PRODUCT_CATEGORY_LABELS, category_icons=PRODUCT_CATEGORY_ICONS)

    # ฟอร์มส่งมาเป็นรายบรรทัด (เพิ่ม/ลบบรรทัดได้อิสระฝั่ง JS) — คีย์คือ sku_<idx>, qty_<idx>, price_<idx>
    line_indexes = sorted({
        key.split("_", 1)[1] for key in form if key.startswith("sku_") and form.get(key)
    })
    line_items = []
    for idx in line_indexes:
        sku = (form.get(f"sku_{idx}") or "").strip()
        if not sku:
            continue
        part = parts_by_sku.get(sku)
        if not part:
            return with_error("มีสินค้าที่เลือกไม่ถูกต้อง หรือไม่ได้อยู่ในคลังของศูนย์นี้ กรุณาเลือกจากรายการค้นหาใหม่")
        qty_raw = (form.get(f"qty_{idx}") or "").strip()
        if not qty_raw:
            continue
        try:
            qty = int(float(qty_raw))
        except ValueError:
            return with_error(f"จำนวนของ '{part['part_name']}' ต้องเป็นตัวเลข")
        if qty <= 0:
            continue
        price_raw = (form.get(f"price_{idx}") or "").strip()
        try:
            unit_price = float(price_raw) if price_raw else part["cost_price"]
        except ValueError:
            return with_error(f"ราคาต่อหน่วยของ '{part['part_name']}' ต้องเป็นตัวเลข")
        line_items.append((sku, qty, unit_price))

    if not line_items:
        return with_error("กรุณาเพิ่มอย่างน้อย 1 รายการสินค้า พร้อมระบุจำนวนที่ต้องการจัดส่ง")

    # แอดมิน (HQ) เป็นผู้สร้างคำสั่งซื้อนี้เอง -> เริ่มที่สถานะ "processing" ทันที (ข้ามขั้น "รอ HQ ดำเนินการ"
    # เพราะ HQ เริ่มเองอยู่แล้ว ไม่ต้องรอตัวเอง) -> แอดมินกดยืนยันจัดส่งต่อได้เลยที่หน้ารายการคำสั่งซื้อ
    cur = conn.execute(
        "INSERT INTO Restock_Orders (center_id, requested_by, status, notes, created_at, processed_at) "
        "VALUES (?,?,'processing',?,?,?)",
        (center_id, user["user_id"], form.get("notes", "").strip() or None, db.now(), db.now()),
    )
    order_id = cur.lastrowid
    for sku, qty, unit_price in line_items:
        conn.execute(
            "INSERT INTO Restock_Order_Items (order_id, part_sku, quantity_requested, unit_price) VALUES (?,?,?,?)",
            (order_id, sku, qty, unit_price),
        )
    conn.commit()
    raise Redirect(f"/admin/restock-orders/{order_id}")


@route("GET", r"/admin/restock-orders/(\d+)")
def admin_restock_order_detail(environ, m, conn, user):
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = conn.execute(
        """SELECT ro.*, sc.name AS center_name, u.name AS requested_by_name
           FROM Restock_Orders ro
           JOIN Service_Centers sc ON sc.center_id = ro.center_id
           JOIN Users u ON u.user_id = ro.requested_by
           WHERE ro.order_id=?""",
        (order_id,),
    ).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    items = conn.execute(
        """SELECT roi.*, sp.part_name FROM Restock_Order_Items roi
           JOIN Spare_Parts sp ON sp.part_sku = roi.part_sku
           WHERE roi.order_id=? ORDER BY roi.item_id""",
        (order_id,),
    ).fetchall()
    total_amount = sum((it["quantity_requested"] or 0) * (it["unit_price"] or 0) for it in items)
    parts = _load_parts(conn, center_id=order["center_id"])
    return render("admin_restock_order_detail.html", user=user, order=order, items=items,
                  total_amount=total_amount,
                  status_label=RESTOCK_STATUS_LABELS.get(order["status"], order["status"]),
                  parts=parts, parts_for_js=_parts_for_js_with_category(parts),
                  category_labels=PRODUCT_CATEGORY_LABELS, category_icons=PRODUCT_CATEGORY_ICONS)


@route("POST", r"/admin/restock-orders/(\d+)/edit")
def admin_restock_order_edit(environ, m, conn, user):
    """แก้ไขหมายเหตุของคำสั่งซื้อ — แก้ไขได้ทุกสถานะ (ปรับสถานะ/เลขติดตามพัสดุใช้ปุ่มดำเนินการ/ยืนยันจัดส่งแทน)"""
    require_login(user, "admin")
    order_id = int(m.group(1))
    _get_restock_order_or_404(conn, order_id)
    form = parse_post(environ)
    conn.execute("UPDATE Restock_Orders SET notes=? WHERE order_id=?",
                 (form.get("notes", "").strip() or None, order_id))
    conn.commit()
    raise Redirect(f"/admin/restock-orders/{order_id}")


@route("POST", r"/admin/restock-orders/(\d+)/item/add")
def admin_restock_order_item_add(environ, m, conn, user):
    """เพิ่มรายการสินค้าใหม่เข้าคำสั่งซื้อที่มีอยู่แล้ว — เพิ่มได้ทุกสถานะ"""
    require_login(user, "admin")
    order_id = int(m.group(1))
    _get_restock_order_or_404(conn, order_id)
    form = parse_post(environ)
    sku = (form.get("sku") or "").strip()
    if not sku:
        raise Redirect(f"/admin/restock-orders/{order_id}")
    part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(400, "ไม่พบสินค้านี้")
    try:
        qty = int(float(form.get("quantity", "")))
    except ValueError:
        raise Redirect(f"/admin/restock-orders/{order_id}")
    if qty <= 0:
        raise Redirect(f"/admin/restock-orders/{order_id}")
    price_raw = (form.get("unit_price") or "").strip()
    try:
        unit_price = float(price_raw) if price_raw else part["cost_price"]
    except ValueError:
        unit_price = part["cost_price"]
    conn.execute(
        "INSERT INTO Restock_Order_Items (order_id, part_sku, quantity_requested, unit_price) VALUES (?,?,?,?)",
        (order_id, sku, qty, unit_price),
    )
    conn.commit()
    raise Redirect(f"/admin/restock-orders/{order_id}")


@route("POST", r"/admin/restock-orders/(\d+)/item/(\d+)/edit")
def admin_restock_order_item_edit(environ, m, conn, user):
    """แก้ไขจำนวน/ราคาต่อหน่วยของรายการสินค้าในคำสั่งซื้อ — แก้ไขได้ทุกสถานะ ถ้าคำสั่งซื้อนี้ "ได้รับของแล้ว"
    (received) และมีการแก้ไขจำนวนที่ได้รับ (quantity_received) ด้วย สต็อกของสินค้าจะถูกปรับตามส่วนต่าง
    จำนวนใหม่-เก่าโดยอัตโนมัติ (กันสต็อกเพี้ยนเพราะสต็อกเพิ่มไปแล้วตอนกดยืนยันรับของ)"""
    require_login(user, "admin")
    order_id, item_id = int(m.group(1)), int(m.group(2))
    order = _get_restock_order_or_404(conn, order_id)
    item = conn.execute("SELECT * FROM Restock_Order_Items WHERE item_id=? AND order_id=?",
                         (item_id, order_id)).fetchone()
    if not item:
        raise HttpError(404, "ไม่พบรายการสินค้านี้ในคำสั่งซื้อ")
    form = parse_post(environ)
    try:
        new_qty = int(form.get("quantity_requested", ""))
        new_price = float(form.get("unit_price", ""))
    except ValueError:
        raise Redirect(f"/admin/restock-orders/{order_id}")
    if new_qty <= 0:
        raise Redirect(f"/admin/restock-orders/{order_id}")

    new_received = item["quantity_received"]
    if order["status"] == "received":
        received_raw = (form.get("quantity_received") or "").strip()
        if received_raw:
            try:
                candidate = int(received_raw)
            except ValueError:
                candidate = item["quantity_received"]
            if candidate != item["quantity_received"]:
                delta = candidate - (item["quantity_received"] or 0)
                part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (item["part_sku"],)).fetchone()
                if delta > 0 and part and part["stock_quantity"] < delta:
                    raise HttpError(
                        400, f"สต็อก '{part['part_name']}' เหลือไม่พอ (เหลือ {part['stock_quantity']} ต้องการเพิ่มอีก {delta})"
                    )
                conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
                             (delta, item["part_sku"]))
                new_received = candidate

    conn.execute(
        "UPDATE Restock_Order_Items SET quantity_requested=?, unit_price=?, quantity_received=? WHERE item_id=?",
        (new_qty, new_price, new_received, item_id),
    )
    conn.commit()
    raise Redirect(f"/admin/restock-orders/{order_id}")


@route("POST", r"/admin/restock-orders/(\d+)/item/(\d+)/delete")
def admin_restock_order_item_delete(environ, m, conn, user):
    """ลบรายการสินค้า 1 ชิ้นออกจากคำสั่งซื้อ — ถ้าคำสั่งซื้อนี้ได้รับของแล้ว (received) และรายการนี้เคยรับของแล้ว
    สต็อกจะถูกหักคืนออกโดยอัตโนมัติก่อนลบ (กันสต็อกเพี้ยน)"""
    require_login(user, "admin")
    order_id, item_id = int(m.group(1)), int(m.group(2))
    order = _get_restock_order_or_404(conn, order_id)
    item = conn.execute("SELECT * FROM Restock_Order_Items WHERE item_id=? AND order_id=?",
                         (item_id, order_id)).fetchone()
    if not item:
        raise HttpError(404, "ไม่พบรายการสินค้านี้ในคำสั่งซื้อ")
    if order["status"] == "received" and item["quantity_received"]:
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?",
                     (item["quantity_received"], item["part_sku"]))
    conn.execute("DELETE FROM Restock_Order_Items WHERE item_id=?", (item_id,))
    conn.commit()
    raise Redirect(f"/admin/restock-orders/{order_id}")


@route("POST", r"/admin/restock-orders/(\d+)/delete")
def admin_restock_order_delete(environ, m, conn, user):
    """ลบคำสั่งซื้อทั้งรายการ — ลบได้ทุกสถานะ ถ้าคำสั่งซื้อนี้ได้รับของแล้ว (received) สต็อกของทุกรายการ
    ที่เคยรับของแล้วจะถูกหักคืนออกโดยอัตโนมัติก่อนลบ (กันสต็อกเพี้ยน)"""
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = _get_restock_order_or_404(conn, order_id)
    items = conn.execute("SELECT * FROM Restock_Order_Items WHERE order_id=?", (order_id,)).fetchall()
    if order["status"] == "received":
        for it in items:
            if it["quantity_received"]:
                conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?",
                             (it["quantity_received"], it["part_sku"]))
    conn.execute("DELETE FROM Restock_Order_Items WHERE order_id=?", (order_id,))
    conn.execute("DELETE FROM Restock_Orders WHERE order_id=?", (order_id,))
    conn.commit()
    raise Redirect("/admin/restock-orders")


@route("GET", r"/admin/restock-orders/(\d+)/delivery-note")
def admin_restock_delivery_note(environ, m, conn, user):
    """หน้าพิมพ์ "ใบส่งสินค้า" — ผู้ส่ง (ผู้ออก) = ศูนย์บริการที่ตั้งเป็นสำนักงานใหญ่ (is_headquarters=1),
    ผู้รับ = ศูนย์บริการปลายทางของคำสั่งซื้อนี้ — ใช้หน้าเว็บสำหรับพิมพ์ + ปุ่ม "พิมพ์/บันทึกเป็น PDF"
    ของเบราว์เซอร์ผู้ใช้เอง เหมือนใบเสนอราคา/ใบแจ้งหนี้ (ดูหมายเหตุที่ต้นไฟล์หัวข้อ "printable PDF views")"""
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = conn.execute(
        """SELECT ro.*, sc.name AS center_name, sc.address AS center_address, sc.phone AS center_phone,
                  sc.tax_id AS center_tax_id, u.name AS requested_by_name
           FROM Restock_Orders ro
           JOIN Service_Centers sc ON sc.center_id = ro.center_id
           JOIN Users u ON u.user_id = ro.requested_by
           WHERE ro.order_id=?""",
        (order_id,),
    ).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบคำสั่งซื้อนี้")
    hq = _get_hq_center(conn)
    if not hq:
        raise HttpError(
            400,
            "ยังไม่ได้กำหนดศูนย์บริการที่เป็น \"สำนักงานใหญ่\" — กรุณาไปตั้งค่าที่หน้า \"ศูนย์บริการ\" "
            "(ติ๊ก \"ตั้งเป็นสำนักงานใหญ่\" ที่สาขาที่ต้องการใช้เป็นผู้ส่ง) ก่อนพิมพ์ใบส่งสินค้า",
        )
    items = conn.execute(
        """SELECT roi.*, sp.part_name FROM Restock_Order_Items roi
           JOIN Spare_Parts sp ON sp.part_sku = roi.part_sku
           WHERE roi.order_id=? ORDER BY roi.item_id""",
        (order_id,),
    ).fetchall()
    total = sum((it["quantity_requested"] or 0) * (it["unit_price"] or 0) for it in items)
    return render("delivery_note_print.html", order=order, hq=hq, items=items, total=round(total, 2))


# ขั้นที่ 5 "รายงานยอดขาย/ชำระเงินฝากขาย": ศูนย์บริการส่งรายงานยอดขายสินค้าฝากขายประจำเดือน (คำนวณอัตโนมัติจาก
# ยอดขายที่ ownership='consignment' ในเดือนนั้น) -> HQ ตรวจสอบกระทบยอด+ออกเลขที่ใบแจ้งหนี้ -> ศูนย์บริการโอนเงินจริง
# นอกระบบ -> HQ กดยืนยันว่าได้รับชำระเงินแล้ว (ระบบนี้ติดตามแค่สถานะ ไม่ได้เชื่อมธนาคารจริง)

CONSIGNMENT_STATUS_LABELS = {
    "draft": "📝 ร่าง (ยังไม่ส่ง)",
    "submitted": "📨 ส่งรายงานแล้ว รอ HQ ตรวจสอบ",
    "reconciled": "🔎 HQ ตรวจสอบแล้ว รอชำระเงิน",
    "paid": "✅ ชำระเงินเรียบร้อย",
}


def _current_period_month():
    return datetime.datetime.now().strftime("%Y-%m")


def _next_period_month(period_month):
    y, mo = period_month.split("-")
    y, mo = int(y), int(mo)
    if mo == 12:
        return f"{y + 1}-01"
    return f"{y}-{mo + 1:02d}"


def _consignment_sales_total(conn, center_id, period_month):
    """รวมยอดขายสินค้าฝากขาย (ownership='consignment') ของศูนย์บริการในเดือนที่ระบุ (period_month 'YYYY-MM')
    ใช้คำนวณยอดตั้งต้นให้ผู้จัดการเห็นก่อนกดส่งรายงาน — คิดจากยอดขายทั้งหมด (ไม่หักคอมมิชชั่น) เพราะเป็นยอดที่ต้องนำส่ง HQ"""
    row = conn.execute(
        """SELECT COALESCE(SUM(si.quantity * si.unit_price), 0) AS total
           FROM Sale_Items si
           JOIN Sales_Orders so ON so.order_id = si.order_id
           JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
           WHERE so.center_id = ? AND sp.ownership = 'consignment'
             AND so.created_at >= ? AND so.created_at < ?""",
        (center_id, f"{period_month}-01 00:00:00", f"{_next_period_month(period_month)}-01 00:00:00"),
    ).fetchone()
    return row["total"] or 0


@route("GET", r"/manager/settlements")
def manager_settlements(environ, m, conn, user):
    require_login(user, "manager")
    center_id = user.get("center_id")
    if not center_id:
        raise HttpError(403, "บัญชีนี้ยังไม่ได้ถูกกำหนดศูนย์บริการ")
    period = _current_period_month()
    current = conn.execute(
        "SELECT * FROM Consignment_Settlements WHERE center_id=? AND period_month=?", (center_id, period)
    ).fetchone()
    current_total = _consignment_sales_total(conn, center_id, period)
    history = conn.execute(
        "SELECT * FROM Consignment_Settlements WHERE center_id=? AND period_month != ? ORDER BY period_month DESC",
        (center_id, period),
    ).fetchall()
    return render(
        "manager_settlements.html", user=user, period=period, current=current, current_total=current_total,
        history=history, settlement_status_labels=CONSIGNMENT_STATUS_LABELS,
    )


@route("POST", r"/manager/settlements/submit")
def manager_settlement_submit(environ, m, conn, user):
    require_login(user, "manager")
    center_id = user.get("center_id")
    if not center_id:
        raise HttpError(403, "บัญชีนี้ยังไม่ได้ถูกกำหนดศูนย์บริการ")
    period = _current_period_month()
    total = _consignment_sales_total(conn, center_id, period)
    form = parse_post(environ)
    notes = form.get("notes", "").strip() or None
    existing = conn.execute(
        "SELECT * FROM Consignment_Settlements WHERE center_id=? AND period_month=?", (center_id, period)
    ).fetchone()
    if existing:
        if existing["status"] != "draft":
            raise HttpError(400, "ส่งรายงานยอดขายเดือนนี้ไปแล้ว")
        conn.execute(
            """UPDATE Consignment_Settlements
               SET total_consignment_sales=?, status='submitted', submitted_by=?, submitted_at=?, notes=?
               WHERE settlement_id=?""",
            (total, user["user_id"], db.now(), notes, existing["settlement_id"]),
        )
    else:
        conn.execute(
            """INSERT INTO Consignment_Settlements
               (center_id, period_month, total_consignment_sales, status, submitted_by, submitted_at, notes)
               VALUES (?,?,?,'submitted',?,?,?)""",
            (center_id, period, total, user["user_id"], db.now(), notes),
        )
    conn.commit()
    raise Redirect("/manager/settlements")


@route("GET", r"/admin/settlements")
def admin_settlements(environ, m, conn, user):
    require_login(user, "admin")
    settlements = conn.execute(
        """SELECT cs.*, sc.name AS center_name, us.name AS submitted_by_name, ur.name AS reconciled_by_name
           FROM Consignment_Settlements cs
           JOIN Service_Centers sc ON sc.center_id = cs.center_id
           LEFT JOIN Users us ON us.user_id = cs.submitted_by
           LEFT JOIN Users ur ON ur.user_id = cs.reconciled_by
           WHERE cs.status != 'draft'
           ORDER BY (cs.status='submitted') DESC, cs.period_month DESC"""
    ).fetchall()
    return render("admin_settlements.html", user=user, settlements=settlements, settlement_status_labels=CONSIGNMENT_STATUS_LABELS)


@route("POST", r"/admin/settlements/(\d+)/reconcile")
def admin_settlement_reconcile(environ, m, conn, user):
    require_login(user, "admin")
    settlement_id = int(m.group(1))
    s = conn.execute("SELECT * FROM Consignment_Settlements WHERE settlement_id=?", (settlement_id,)).fetchone()
    if not s:
        raise HttpError(404, "ไม่พบรายงานนี้")
    if s["status"] != "submitted":
        raise HttpError(400, "ตรวจสอบกระทบยอดได้เฉพาะรายงานที่ส่งมาแล้วและยังไม่ได้ตรวจสอบเท่านั้น")
    form = parse_post(environ)
    invoice_number = form.get("invoice_number", "").strip()
    conn.execute(
        """UPDATE Consignment_Settlements SET status='reconciled', reconciled_by=?, reconciled_at=?, invoice_number=?
           WHERE settlement_id=?""",
        (user["user_id"], db.now(), invoice_number or None, settlement_id),
    )
    conn.commit()
    raise Redirect("/admin/settlements")


@route("POST", r"/admin/settlements/(\d+)/mark-paid")
def admin_settlement_mark_paid(environ, m, conn, user):
    require_login(user, "admin")
    settlement_id = int(m.group(1))
    s = conn.execute("SELECT * FROM Consignment_Settlements WHERE settlement_id=?", (settlement_id,)).fetchone()
    if not s:
        raise HttpError(404, "ไม่พบรายงานนี้")
    if s["status"] != "reconciled":
        raise HttpError(400, "ยืนยันรับชำระเงินได้เฉพาะรายงานที่ตรวจสอบกระทบยอดแล้วเท่านั้น")
    conn.execute("UPDATE Consignment_Settlements SET status='paid', paid_at=? WHERE settlement_id=?",
                 (db.now(), settlement_id))
    conn.commit()
    raise Redirect("/admin/settlements")


# --------------------------------------------------- ทรัพยากรโปรโมท (HQ -> ศูนย์บริการ) --
# แอดมิน (HQ) อัปโหลด/แนบทรัพยากรไว้ให้ศูนย์บริการ (ผู้จัดการ/เซล) ดาวน์โหลดไปใช้โปรโมทหน้าร้าน/โซเชียล
# 'Brochure'/'Document' เก็บเป็นไฟล์จริง (รูปภาพ/PDF), 'Video' เก็บเป็นลิงก์ภายนอกเท่านั้น (ดู schema.sql)

RESOURCE_TYPE_LABELS = {
    "Brochure": "🖼️ โบรชัวร์/รูปภาพ",
    "Document": "📄 เอกสาร PDF",
    "Video": "🎬 วิดีโอ",
}
RESOURCE_TYPES = ["Brochure", "Document", "Video"]


def _resources_by_type(conn):
    """โหลดทรัพยากรโปรโมททั้งหมด จัดกลุ่มตามประเภทไฟล์ (Brochure/Document/Video) — เรียงใหม่สุดก่อนในแต่ละกลุ่ม"""
    rows = conn.execute(
        """SELECT r.*, u.name AS uploaded_by_name FROM Marketing_Resources r
           JOIN Users u ON u.user_id = r.uploaded_by
           ORDER BY r.created_at DESC"""
    ).fetchall()
    grouped = {t: [] for t in RESOURCE_TYPES}
    for r in rows:
        grouped.setdefault(r["resource_type"], []).append(r)
    # หมายเหตุ: ใช้คีย์ "resources" ไม่ใช่ "items" เพราะ "items" ชนกับ dict.items() ในตัว — ถ้าใช้ชื่อนี้
    # Jinja จะ resolve g.items เป็น bound method ของ dict (ผ่าน getattr ก่อน) แทนที่จะเป็นค่าที่ตั้งใจไว้
    return [
        {"type": t, "label": RESOURCE_TYPE_LABELS.get(t, t), "resources": grouped.get(t, [])}
        for t in RESOURCE_TYPES
    ]


@route("GET", r"/admin/resources")
def admin_resources(environ, m, conn, user):
    require_login(user, "admin")
    return render("admin_resources.html", user=user, groups=_resources_by_type(conn),
                   resource_types=RESOURCE_TYPES, resource_type_labels=RESOURCE_TYPE_LABELS, error=None)


@route("POST", r"/admin/resources/new")
def admin_resources_new(environ, m, conn, user):
    require_login(user, "admin")
    fields, files = parse_multipart(environ)

    def with_error(msg):
        return render("admin_resources.html", user=user, groups=_resources_by_type(conn),
                       resource_types=RESOURCE_TYPES, resource_type_labels=RESOURCE_TYPE_LABELS, error=msg)

    title = fields.get("title", "").strip()
    resource_type = fields.get("resource_type", "").strip()
    if not title:
        return with_error("กรุณากรอกชื่อรายการ")
    if resource_type not in RESOURCE_TYPES:
        return with_error("กรุณาเลือกประเภททรัพยากรให้ถูกต้อง")

    description = fields.get("description", "").strip() or None
    file_filename = None
    video_url = None

    if resource_type == "Video":
        video_url = fields.get("video_url", "").strip()
        if not video_url:
            return with_error("กรุณาใส่ลิงก์วิดีโอ (เช่น YouTube/Facebook/Google Drive)")
        if not (video_url.startswith("http://") or video_url.startswith("https://")):
            return with_error("ลิงก์วิดีโอต้องขึ้นต้นด้วย http:// หรือ https://")
    else:
        resource_file = (files.get("file") or [None])[0]
        try:
            file_filename = save_marketing_file(resource_file)
        except ValueError as e:
            return with_error(str(e))
        if not file_filename:
            return with_error("กรุณาแนบไฟล์ (รูปภาพหรือ PDF)")

    conn.execute(
        "INSERT INTO Marketing_Resources (title, description, resource_type, file_filename, video_url, "
        "uploaded_by, created_at) VALUES (?,?,?,?,?,?,?)",
        (title, description, resource_type, file_filename, video_url, user["user_id"], db.now()),
    )
    conn.commit()
    raise Redirect("/admin/resources")


@route("POST", r"/admin/resources/(\d+)/edit")
def admin_resources_edit(environ, m, conn, user):
    require_login(user, "admin")
    resource_id = int(m.group(1))
    fields, files = parse_multipart(environ)

    def with_error(msg):
        return render("admin_resources.html", user=user, groups=_resources_by_type(conn),
                       resource_types=RESOURCE_TYPES, resource_type_labels=RESOURCE_TYPE_LABELS, error=msg)

    existing = conn.execute("SELECT * FROM Marketing_Resources WHERE resource_id=?", (resource_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบทรัพยากรนี้")

    title = fields.get("title", "").strip()
    if not title:
        return with_error("กรุณากรอกชื่อรายการ")
    description = fields.get("description", "").strip() or None

    # ประเภททรัพยากร (Brochure/Document/Video) แก้ไขไม่ได้หลังสร้างแล้ว เพื่อกันความสับสนระหว่างไฟล์แนบ
    # กับลิงก์วิดีโอ — ถ้าต้องการเปลี่ยนประเภท ให้ลบรายการเดิมแล้วสร้างใหม่แทน
    file_filename = existing["file_filename"]
    video_url = existing["video_url"]
    if existing["resource_type"] == "Video":
        new_url = fields.get("video_url", "").strip()
        if not new_url:
            return with_error("กรุณาใส่ลิงก์วิดีโอ (เช่น YouTube/Facebook/Google Drive)")
        if not (new_url.startswith("http://") or new_url.startswith("https://")):
            return with_error("ลิงก์วิดีโอต้องขึ้นต้นด้วย http:// หรือ https://")
        video_url = new_url
    else:
        resource_file = (files.get("file") or [None])[0]
        try:
            new_file = save_marketing_file(resource_file)
        except ValueError as e:
            return with_error(str(e))
        if new_file:
            _delete_marketing_file(file_filename)
            file_filename = new_file

    conn.execute(
        "UPDATE Marketing_Resources SET title=?, description=?, file_filename=?, video_url=? WHERE resource_id=?",
        (title, description, file_filename, video_url, resource_id),
    )
    conn.commit()
    raise Redirect("/admin/resources")


@route("POST", r"/admin/resources/(\d+)/delete")
def admin_resources_delete(environ, m, conn, user):
    require_login(user, "admin")
    resource_id = int(m.group(1))
    existing = conn.execute("SELECT * FROM Marketing_Resources WHERE resource_id=?", (resource_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบทรัพยากรนี้")
    _delete_marketing_file(existing["file_filename"])
    conn.execute("DELETE FROM Marketing_Resources WHERE resource_id=?", (resource_id,))
    conn.commit()
    raise Redirect("/admin/resources")


@route("GET", r"/resources")
def resources_browse(environ, m, conn, user):
    """หน้าดูทรัพยากรโปรโมทสำหรับผู้จัดการ/เซลที่ศูนย์บริการ — ดู/ดาวน์โหลดได้อย่างเดียว แก้ไข/ลบไม่ได้
    (ตารางเดิม — แทนที่ด้วยโมดูล ShareSpace ด้านล่างแล้ว ไม่มีเมนูเข้าถึงเส้นทางนี้อีก แต่คงไว้เผื่อมีลิงก์เก่าค้าง)"""
    require_login(user, "admin", "manager", "sales")
    return render("resources.html", user=user, groups=_resources_by_type(conn))


def _save_activity_files(conn, activity_id, files, user, category=None):
    """บันทึกไฟล์แนบที่อัปโหลดมาพร้อมฟอร์มกิจกรรม ShareSpace ลงดิสก์ พร้อมบันทึกแถวในตาราง Activity_Files
    เรียกได้ทั้งตอนสร้างกิจกรรมใหม่และตอนแก้ไข (เพิ่มไฟล์เข้ากิจกรรมเดิม)
    - ถ้าระบุ category ('marketing'/'technical') คือกิจกรรมแบบใหม่ที่แยกหมวดแล้ว จะอ่านไฟล์จาก field เดียว
      ชื่อ 'activity_files' แล้วบันทึกลงหมวดนั้นทั้งหมด
    - ถ้าไม่ระบุ (None) คือกิจกรรมแบบเก่าก่อนแยกหมวด (ผสม) จะอ่านจาก field เดิมสองชื่อ
      'marketing_files'/'technical_files' ตามหมวดของแต่ละก้อน (โหมด legacy เพื่อไม่ให้ฟอร์มเก่าที่ยังไม่ได้แยกพัง)"""
    pairs = [(category, "activity_files")] if category else \
        [("marketing", "marketing_files"), ("technical", "technical_files")]
    for cat, field_name in pairs:
        for f in files.get(field_name) or []:
            saved = save_activity_file(f)
            if not saved:
                continue
            stored_name, size_bytes = saved
            conn.execute(
                "INSERT INTO Activity_Files (activity_id, category, filename, stored_name, size_bytes, "
                "uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?)",
                (activity_id, cat, f["filename"], stored_name, size_bytes, user["user_id"], db.now()),
            )


ACTIVITY_CATEGORY_LABELS = {"marketing": "📣 Marketing", "technical": "🔧 Technical"}


def _valid_activity_category(raw):
    """ตรวจ query string ?category= ให้เหลือแค่ 'marketing'/'technical' เท่านั้น — ค่าอื่นๆ/ไม่ระบุ ถือว่า
    ไม่ถูกต้อง (คืน None ให้ผู้เรียกไป fallback เป็นค่าเริ่มต้นเอง)"""
    return raw if raw in ("marketing", "technical") else None


@route("GET", r"/admin/activities")
def admin_activities(environ, m, conn, user):
    """ShareSpace — รายการกิจกรรม (แอดมิน) แยกแท็บ Marketing/Technical ต่างหากตามรูปอ้างอิง เพื่อให้กำหนด
    สิทธิ์ชัดเจน — กิจกรรมเก่าก่อนแยกหมวด (category IS NULL, มีไฟล์ผสมทั้งสองหมวด) จะโผล่ในทั้งสองแท็บ
    พร้อมป้าย "ผสม (เดิม)" ให้สังเกตง่าย — รองรับค้นหา (q), กรองช่วงวันที่จัดกิจกรรม (from/to ค่าเริ่มต้นเดือน
    ปัจจุบัน ใช้ month_date_range เหมือนหน้าอื่นๆ ในระบบ), กรองสถานะ (status) และเรียงลำดับ (sort) ตามรูปอ้างอิงใหม่ —
    ส่ง marketing_size_bytes/technical_size_bytes แยกตามหมวด เพื่อให้เทมเพลตแสดงปุ่มดาวน์โหลดไฟล์ (zip) ของ
    แท็บที่กำลังดูอยู่ได้โดยตรงจากหน้ารายการ (แอดมินดาวน์โหลดได้ทุกกิจกรรมแม้เป็นฉบับร่าง — ดู serve_sharespace_zip)"""
    require_login(user, "admin")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    tab = _valid_activity_category(qs.get("tab", [""])[0]) or "marketing"
    q = (qs.get("q", [""])[0] or "").strip()
    status_filter = qs.get("status", [""])[0]
    if status_filter not in ("draft", "published"):
        status_filter = "all"
    sort = qs.get("sort", [""])[0]
    if sort not in ("event_date", "name"):
        sort = "latest"
    _from_sql, _to_sql, date_from, date_to = month_date_range(environ)

    where = ["(a.category = ? OR a.category IS NULL)"]
    params = [tab]
    where.append("SUBSTR(COALESCE(a.event_date, a.created_at), 1, 10) BETWEEN ? AND ?")
    params += [date_from, date_to]
    if status_filter != "all":
        where.append("a.status = ?")
        params.append(status_filter)
    if q:
        like = f"%{q}%"
        where.append("(a.title ILIKE ? OR COALESCE(a.marketing_description,'') ILIKE ? "
                      "OR COALESCE(a.technical_description,'') ILIKE ?)")
        params += [like, like, like]

    order_by = "a.created_at DESC"
    if sort == "event_date":
        order_by = "a.event_date DESC NULLS LAST, a.created_at DESC"
    elif sort == "name":
        order_by = "a.title ASC"

    rows = conn.execute(
        f"""SELECT a.*, u.name AS created_by_name,
             (SELECT COUNT(*) FROM Activity_Files f WHERE f.activity_id=a.activity_id AND f.category='marketing') AS marketing_count,
             (SELECT COUNT(*) FROM Activity_Files f WHERE f.activity_id=a.activity_id AND f.category='technical') AS technical_count,
             (SELECT COALESCE(SUM(f.size_bytes), 0) FROM Activity_Files f WHERE f.activity_id=a.activity_id) AS total_size_bytes,
             (SELECT COALESCE(SUM(f.size_bytes), 0) FROM Activity_Files f WHERE f.activity_id=a.activity_id AND f.category='marketing') AS marketing_size_bytes,
             (SELECT COALESCE(SUM(f.size_bytes), 0) FROM Activity_Files f WHERE f.activity_id=a.activity_id AND f.category='technical') AS technical_size_bytes
           FROM Activities a LEFT JOIN Users u ON u.user_id = a.created_by
           WHERE {' AND '.join(where)}
           ORDER BY {order_by}""",
        tuple(params),
    ).fetchall()
    return render("admin_activities.html", user=user, activities=rows, tab=tab,
                   category_labels=ACTIVITY_CATEGORY_LABELS, q=q, status_filter=status_filter,
                   sort=sort, date_from=date_from, date_to=date_to)


@route("GET", r"/admin/activities/new")
def admin_activity_new_form(environ, m, conn, user):
    require_login(user, "admin")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    category = _valid_activity_category(qs.get("category", [""])[0]) or "marketing"
    return render("admin_activity_form.html", user=user, activity=None, error=None,
                   category=category, category_labels=ACTIVITY_CATEGORY_LABELS)


@route("POST", r"/admin/activities/new")
def admin_activity_new_submit(environ, m, conn, user):
    require_login(user, "admin")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    category = _valid_activity_category(qs.get("category", [""])[0]) or "marketing"
    fields, files = parse_multipart(environ)

    def with_error(msg):
        return render("admin_activity_form.html", user=user, activity=None, error=msg,
                       category=category, category_labels=ACTIVITY_CATEGORY_LABELS)

    title = fields.get("title", "").strip()
    if not title:
        return with_error("กรุณากรอกชื่อกิจกรรม")

    event_date = fields.get("event_date", "").strip() or None
    download_deadline = fields.get("download_deadline", "").strip() or None
    description = fields.get("description", "").strip() or None
    marketing_description = description if category == "marketing" else None
    technical_description = description if category == "technical" else None
    action = fields.get("action", "draft")
    status = "published" if action == "publish" else "draft"
    is_public = 1 if fields.get("is_public") else 0
    now = db.now()
    published_at = now if status == "published" else None

    cur = conn.execute(
        "INSERT INTO Activities (title, category, event_date, download_deadline, marketing_description, "
        "technical_description, status, is_public, created_by, created_at, published_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (title, category, event_date, download_deadline, marketing_description, technical_description,
         status, is_public, user["user_id"], now, published_at),
    )
    activity_id = cur.lastrowid

    try:
        _save_activity_files(conn, activity_id, files, user, category=category)
    except ValueError as e:
        # กิจกรรมสร้างไปแล้วแต่ไฟล์บางไฟล์มีปัญหา (ชนิด/ขนาดไม่ผ่าน) — ยกเลิกทั้งหมดแล้วแจ้ง error กลับฟอร์มเดิม
        conn.rollback()
        return with_error(str(e))

    conn.commit()
    raise Redirect(f"/admin/activities/{activity_id}/edit")


@route("GET", r"/admin/activities/(\d+)/edit")
def admin_activity_edit_form(environ, m, conn, user):
    require_login(user, "admin")
    activity_id = int(m.group(1))
    activity = _activity_with_files(conn, activity_id)
    if not activity:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    return render("admin_activity_form.html", user=user, activity=activity, error=None,
                   category=activity["category"], category_labels=ACTIVITY_CATEGORY_LABELS)


@route("POST", r"/admin/activities/(\d+)/edit")
def admin_activity_edit_submit(environ, m, conn, user):
    require_login(user, "admin")
    activity_id = int(m.group(1))
    existing = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    category = existing["category"]  # กิจกรรมที่สร้างไปแล้วเปลี่ยนหมวดไม่ได้ — None = กิจกรรมเก่าแบบผสม (โหมด legacy)
    fields, files = parse_multipart(environ)

    def with_error(msg):
        return render("admin_activity_form.html", user=user, activity=_activity_with_files(conn, activity_id),
                       error=msg, category=category, category_labels=ACTIVITY_CATEGORY_LABELS)

    title = fields.get("title", "").strip()
    if not title:
        return with_error("กรุณากรอกชื่อกิจกรรม")

    event_date = fields.get("event_date", "").strip() or None
    download_deadline = fields.get("download_deadline", "").strip() or None
    if category:
        description = fields.get("description", "").strip() or None
        marketing_description = description if category == "marketing" else existing["marketing_description"]
        technical_description = description if category == "technical" else existing["technical_description"]
    else:
        # โหมด legacy (กิจกรรมผสมเก่า) — ฟอร์มยังมีสองช่องแยกเหมือนเดิม
        marketing_description = fields.get("marketing_description", "").strip() or None
        technical_description = fields.get("technical_description", "").strip() or None
    action = fields.get("action", "")
    status = existing["status"]
    published_at = existing["published_at"]
    if action == "publish":
        status = "published"
        published_at = published_at or db.now()
    elif action == "draft":
        status = "draft"
    is_public = 1 if fields.get("is_public") else 0

    try:
        _save_activity_files(conn, activity_id, files, user, category=category)
    except ValueError as e:
        return with_error(str(e))

    conn.execute(
        "UPDATE Activities SET title=?, event_date=?, download_deadline=?, marketing_description=?, "
        "technical_description=?, status=?, published_at=?, is_public=? WHERE activity_id=?",
        (title, event_date, download_deadline, marketing_description, technical_description,
         status, published_at, is_public, activity_id),
    )
    conn.commit()
    raise Redirect(f"/admin/activities/{activity_id}/edit")


@route("POST", r"/admin/activities/(\d+)/publish")
def admin_activity_publish(environ, m, conn, user):
    require_login(user, "admin")
    activity_id = int(m.group(1))
    existing = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    conn.execute(
        "UPDATE Activities SET status='published', published_at=COALESCE(published_at, ?) WHERE activity_id=?",
        (db.now(), activity_id),
    )
    conn.commit()
    raise Redirect("/admin/activities")


@route("POST", r"/admin/activities/(\d+)/unpublish")
def admin_activity_unpublish(environ, m, conn, user):
    require_login(user, "admin")
    activity_id = int(m.group(1))
    existing = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    conn.execute("UPDATE Activities SET status='draft' WHERE activity_id=?", (activity_id,))
    conn.commit()
    raise Redirect("/admin/activities")


@route("POST", r"/admin/activities/(\d+)/toggle-public")
def admin_activity_toggle_public(environ, m, conn, user):
    """เปิด/ปิดลิงก์สาธารณะ (/s/<activity_id>) ของกิจกรรมนี้ — เปิดแล้วใครก็ตามที่มีลิงก์ดู/ดาวน์โหลดไฟล์ได้
    ทั้งหมวด marketing และ technical โดยไม่ต้อง login (กิจกรรมต้องเผยแพร่แล้วด้วยจึงจะเข้าถึงได้จริง)"""
    require_login(user, "admin")
    activity_id = int(m.group(1))
    existing = conn.execute("SELECT is_public FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    new_value = 0 if existing["is_public"] else 1
    conn.execute("UPDATE Activities SET is_public=? WHERE activity_id=?", (new_value, activity_id))
    conn.commit()
    raise Redirect("/admin/activities")


@route("POST", r"/admin/activities/(\d+)/duplicate")
def admin_activity_duplicate(environ, m, conn, user):
    """คัดลอกกิจกรรม — สร้างกิจกรรมใหม่เป็นฉบับร่าง คัดลอกชื่อ (เติม "(สำเนา)"), หมวด, วันที่, และคำอธิบาย
    จากกิจกรรมเดิม แต่ "ไม่คัดลอกไฟล์แนบ" (ป้องกันพื้นที่จัดเก็บบวมโดยไม่ตั้งใจ) — แอดมินอัปโหลดไฟล์ใหม่เองในหน้าแก้ไข"""
    require_login(user, "admin")
    activity_id = int(m.group(1))
    existing = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    now = db.now()
    cur = conn.execute(
        "INSERT INTO Activities (title, category, event_date, download_deadline, marketing_description, "
        "technical_description, status, created_by, created_at, published_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (existing["title"] + " (สำเนา)", existing["category"], existing["event_date"], existing["download_deadline"],
         existing["marketing_description"], existing["technical_description"], "draft", user["user_id"], now, None),
    )
    new_activity_id = cur.lastrowid
    conn.commit()
    raise Redirect(f"/admin/activities/{new_activity_id}/edit")


@route("POST", r"/admin/activities/(\d+)/delete")
def admin_activity_delete(environ, m, conn, user):
    require_login(user, "admin")
    activity_id = int(m.group(1))
    existing = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบกิจกรรมนี้")
    file_rows = conn.execute("SELECT stored_name FROM Activity_Files WHERE activity_id=?", (activity_id,)).fetchall()
    for f in file_rows:
        _delete_activity_file(f["stored_name"])
    conn.execute("DELETE FROM Activity_Files WHERE activity_id=?", (activity_id,))
    conn.execute("DELETE FROM Activities WHERE activity_id=?", (activity_id,))
    conn.commit()
    raise Redirect("/admin/activities")


@route("POST", r"/admin/activities/(\d+)/files/(\d+)/delete")
def admin_activity_file_delete(environ, m, conn, user):
    require_login(user, "admin")
    activity_id = int(m.group(1))
    file_id = int(m.group(2))
    f = conn.execute(
        "SELECT * FROM Activity_Files WHERE file_id=? AND activity_id=?", (file_id, activity_id)
    ).fetchone()
    if not f:
        raise HttpError(404, "ไม่พบไฟล์นี้")
    _delete_activity_file(f["stored_name"])
    conn.execute("DELETE FROM Activity_Files WHERE file_id=?", (file_id,))
    conn.commit()
    raise Redirect(f"/admin/activities/{activity_id}/edit")


def _activity_publicly_accessible(activity):
    """เงื่อนไขที่กิจกรรมหนึ่งจะเข้าถึงได้ผ่านลิงก์สาธารณะ /s/<id> โดยไม่ต้อง login — ต้องเปิด is_public ไว้,
    เผยแพร่แล้ว (published), และยังไม่เลยกำหนดปิดดาวน์โหลด (ถ้ามีการตั้งไว้)"""
    if not activity or not activity["is_public"] or activity["status"] != "published":
        return False
    if activity["download_deadline"] and activity["download_deadline"] < db.now()[:10]:
        return False
    return True


@route("GET", r"/s/(\d+)")
def public_activity_view(environ, m, conn, user):
    """หน้าดูกิจกรรมสาธารณะ — ไม่ต้อง login เข้าถึงได้ทุกคนที่มีลิงก์ ถ้ากิจกรรมเปิด is_public ไว้ — แสดง
    รายละเอียด + ไฟล์ทั้งสองหมวด (marketing และ technical) พร้อมดาวน์โหลดทีละไฟล์/ทั้งหมดเป็น zip"""
    activity_id = int(m.group(1))
    activity = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not _activity_publicly_accessible(activity):
        raise HttpError(404, "ไม่พบกิจกรรมนี้ หรือลิงก์นี้ไม่เปิดให้เข้าถึงแล้ว")
    marketing_files = conn.execute(
        "SELECT * FROM Activity_Files WHERE activity_id=? AND category='marketing' ORDER BY uploaded_at DESC",
        (activity_id,),
    ).fetchall()
    technical_files = conn.execute(
        "SELECT * FROM Activity_Files WHERE activity_id=? AND category='technical' ORDER BY uploaded_at DESC",
        (activity_id,),
    ).fetchall()
    return render("public_activity.html", user=user, activity=activity,
                   marketing_files=marketing_files, technical_files=technical_files)


@route("GET", r"/sharespace")
def sharespace_browse(environ, m, conn, user):
    """ShareSpace — หน้าดูไฟล์สำหรับ manager/sales (หมวด Marketing) และ technician (หมวด Technical)
    เห็นเฉพาะกิจกรรมที่เผยแพร่แล้ว (status='published') และยังไม่เลยกำหนดปิดดาวน์โหลด (ถ้ามีการตั้งไว้)"""
    require_login(user, "admin", "manager", "sales", "technician")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    today = db.now()[:10]

    if user["role"] in ("manager", "sales"):
        default_tab = "marketing"
        available_tabs = ["marketing"]
    elif user["role"] == "technician":
        default_tab = "technical"
        available_tabs = ["technical"]
    else:  # admin
        default_tab = "marketing"
        available_tabs = ["marketing", "technical"]

    tab = qs.get("tab", [""])[0]
    if tab not in available_tabs:
        tab = default_tab

    rows = conn.execute(
        "SELECT * FROM Activities WHERE status='published' ORDER BY COALESCE(event_date, created_at) DESC"
    ).fetchall()
    activities = []
    for a in rows:
        if a["download_deadline"] and a["download_deadline"] < today:
            continue
        files = conn.execute(
            "SELECT * FROM Activity_Files WHERE activity_id=? AND category=? ORDER BY uploaded_at DESC",
            (a["activity_id"], tab),
        ).fetchall()
        if not files:
            continue
        activities.append({
            "activity_id": a["activity_id"], "title": a["title"], "event_date": a["event_date"],
            "download_deadline": a["download_deadline"],
            "description": a["marketing_description"] if tab == "marketing" else a["technical_description"],
            "files": files,
        })

    return render("sharespace.html", user=user, tab=tab, available_tabs=available_tabs, activities=activities)


def _odoo_sync_counts(conn):
    """นับจำนวนข้อมูลทั้งหมด vs. ที่ซิงก์ไป Odoo แล้ว (มี odoo_*_id ไม่เป็น NULL) แยกตามประเภท —
    ใช้แสดงในหน้า /admin/odoo-sync ให้แอดมินเห็นภาพรวมก่อนกดซิงก์ทั้งหมด"""
    def _count(sql):
        return conn.execute(sql).fetchone()["c"]
    return {
        "customers": {
            "total": _count("SELECT COUNT(*) c FROM Customers"),
            "synced": _count("SELECT COUNT(*) c FROM Customers WHERE odoo_partner_id IS NOT NULL"),
        },
        "products": {
            "total": _count("SELECT COUNT(*) c FROM Spare_Parts"),
            "synced": _count("SELECT COUNT(*) c FROM Spare_Parts WHERE odoo_product_id IS NOT NULL"),
        },
        "staff": {
            "total": _count("SELECT COUNT(*) c FROM Users WHERE role != 'customer'"),
            "synced": _count("SELECT COUNT(*) c FROM Users WHERE role != 'customer' AND odoo_user_id IS NOT NULL"),
        },
        "centers": {
            "total": _count("SELECT COUNT(*) c FROM Service_Centers"),
            "synced": _count("SELECT COUNT(*) c FROM Service_Centers WHERE odoo_partner_id IS NOT NULL"),
        },
    }


@route("GET", r"/admin/odoo-sync")
def admin_odoo_sync(environ, m, conn, user):
    """หน้าซิงก์ข้อมูลไป Odoo แบบรวมศูนย์ — ใช้สำหรับ (1) นำเข้าข้อมูลเดิมที่มีอยู่แล้วก่อนเปิดใช้ฟีเจอร์นี้
    ครั้งเดียว (ลูกค้า/สินค้า/พนักงาน/ศูนย์บริการที่สร้างไว้ก่อนหน้านี้จะยังไม่เคยถูกซิงก์ เพราะการซิงก์
    อัตโนมัติทำงานเฉพาะตอนสร้าง/แก้ไขข้อมูลใหม่เท่านั้น) และ (2) ซิงก์ซ้ำได้ทุกเมื่อถ้าต้องการ (ปลอดภัย —
    ใช้กลไก idempotent matching เดิม ไม่สร้างข้อมูลซ้ำใน Odoo)"""
    require_login(user, "admin")
    return render("admin_odoo_sync.html", user=user, counts=_odoo_sync_counts(conn),
                  odoo_configured=bool(db.ODOO_URL and db.ODOO_DB and db.ODOO_USERNAME and db.ODOO_API_KEY))


@route("POST", r"/admin/odoo-sync/run")
def admin_odoo_sync_run(environ, m, conn, user):
    """ซิงก์ข้อมูลทั้งหมด (ลูกค้า/สินค้า/พนักงาน/ศูนย์บริการ) ไป Odoo ทีเดียว — รันแบบ synchronous ใน
    request เดียว (อาจใช้เวลาสักครู่ถ้ามีข้อมูลเยอะ) แต่ละรายการที่ซิงก์ไม่สำเร็จจะถูกข้ามไปเงียบๆ (ไม่ throw
    ทำให้รายการอื่นซิงก์ต่อไม่ได้) แล้วนับจำนวนสำเร็จ/ไม่สำเร็จมาสรุปแสดงผลในหน้านี้"""
    require_login(user, "admin")
    form = parse_post(environ)

    result = {"customers": [0, 0], "products": [0, 0], "staff": [0, 0], "centers": [0, 0]}  # [ok, fail]

    if form.get("sync_customers"):
        for row in conn.execute("SELECT customer_id FROM Customers").fetchall():
            before = conn.execute(
                "SELECT odoo_partner_id FROM Customers WHERE customer_id=?", (row["customer_id"],)
            ).fetchone()
            _sync_customer_to_odoo(conn, row["customer_id"])
            after = conn.execute(
                "SELECT odoo_partner_id FROM Customers WHERE customer_id=?", (row["customer_id"],)
            ).fetchone()
            idx = 0 if after["odoo_partner_id"] else 1
            result["customers"][idx] += 1

    if form.get("sync_products"):
        for row in conn.execute("SELECT part_sku FROM Spare_Parts").fetchall():
            _sync_product_to_odoo(conn, row["part_sku"])
            after = conn.execute(
                "SELECT odoo_product_id FROM Spare_Parts WHERE part_sku=?", (row["part_sku"],)
            ).fetchone()
            idx = 0 if after["odoo_product_id"] else 1
            result["products"][idx] += 1

    if form.get("sync_staff"):
        for row in conn.execute("SELECT user_id FROM Users WHERE role != 'customer'").fetchall():
            _sync_staff_user_to_odoo(conn, row["user_id"])
            after = conn.execute("SELECT odoo_user_id FROM Users WHERE user_id=?", (row["user_id"],)).fetchone()
            idx = 0 if after["odoo_user_id"] else 1
            result["staff"][idx] += 1

    if form.get("sync_centers"):
        for row in conn.execute("SELECT center_id FROM Service_Centers").fetchall():
            _sync_service_center_to_odoo(conn, row["center_id"])
            after = conn.execute(
                "SELECT odoo_partner_id FROM Service_Centers WHERE center_id=?", (row["center_id"],)
            ).fetchone()
            idx = 0 if after["odoo_partner_id"] else 1
            result["centers"][idx] += 1

    return render("admin_odoo_sync.html", user=user, counts=_odoo_sync_counts(conn), result=result,
                  odoo_configured=bool(db.ODOO_URL and db.ODOO_DB and db.ODOO_USERNAME and db.ODOO_API_KEY))


@route("GET", r"/admin/users")
def admin_users(environ, m, conn, user):
    require_login(user, "admin")
    users = conn.execute(
        """SELECT u.*, c.name AS customer_name, sc.name AS center_name FROM Users u
           LEFT JOIN Customers c ON c.customer_id = u.customer_id
           LEFT JOIN Service_Centers sc ON sc.center_id = u.center_id
           ORDER BY u.role, u.username"""
    ).fetchall()
    customers = conn.execute("SELECT * FROM Customers ORDER BY name").fetchall()
    centers = conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall()
    return render("admin_users.html", users=users, customers=customers, centers=centers, user=user, error=None)


@route("POST", r"/admin/users/new")
def admin_users_new(environ, m, conn, user):
    require_login(user, "admin")
    form = parse_post(environ)
    username = form.get("username", "").strip()
    password = form.get("password", "")
    role = form.get("role", "")
    name = form.get("name", "").strip()
    phone = form.get("phone", "").strip() or None
    customer_id = form.get("customer_id") or None
    center_id = form.get("center_id") or None

    def with_error(msg):
        users = conn.execute(
            """SELECT u.*, c.name AS customer_name, sc.name AS center_name FROM Users u
               LEFT JOIN Customers c ON c.customer_id = u.customer_id
               LEFT JOIN Service_Centers sc ON sc.center_id = u.center_id
               ORDER BY u.role, u.username"""
        ).fetchall()
        customers = conn.execute("SELECT * FROM Customers ORDER BY name").fetchall()
        centers = conn.execute("SELECT * FROM Service_Centers ORDER BY name").fetchall()
        return render("admin_users.html", users=users, customers=customers, centers=centers, user=user, error=msg)

    if not username or not password or not name or role not in ("customer", "admin", "technician", "manager", "sales"):
        return with_error("กรุณากรอกข้อมูลให้ครบถ้วน")
    if len(password) < 8:
        return with_error("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")
    if role == "customer" and not customer_id:
        return with_error("บัญชีลูกค้าต้องเลือกผูกกับข้อมูลลูกค้าที่มีอยู่")
    if role != "customer":
        customer_id = None
    if role == "customer":
        center_id = None  # ศูนย์บริการมีไว้สำหรับ staff เท่านั้น

    try:
        cur = conn.execute(
            "INSERT INTO Users (username, password, role, name, phone, customer_id, center_id, is_active, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
            (username, db.hash_password(password), role, name, phone, customer_id, center_id, db.now()),
        )
        conn.commit()
    except db.IntegrityError:
        return with_error(f"ชื่อผู้ใช้ '{username}' ถูกใช้ไปแล้ว")
    _sync_staff_user_to_odoo(conn, cur.lastrowid)
    raise Redirect("/admin/users")


@route("POST", r"/admin/users/(\d+)/edit")
def admin_users_edit(environ, m, conn, user):
    require_login(user, "admin")
    target_id = int(m.group(1))
    form = parse_post(environ)
    name = form.get("name", "").strip()
    role = form.get("role", "")
    phone = form.get("phone", "").strip() or None
    new_password = form.get("password", "").strip()
    center_id = form.get("center_id") or None
    if role == "customer":
        center_id = None

    if role not in ("customer", "admin", "technician", "manager", "sales") or not name:
        raise Redirect("/admin/users")
    if new_password and len(new_password) < 8:
        raise Redirect("/admin/users")  # รหัสผ่านสั้นเกินไป (<8 ตัวอักษร) -> ไม่บันทึกการเปลี่ยนแปลง

    if new_password:
        conn.execute(
            "UPDATE Users SET name=?, role=?, password=?, phone=?, center_id=? WHERE user_id=?",
            (name, role, db.hash_password(new_password), phone, center_id, target_id),
        )
    else:
        conn.execute("UPDATE Users SET name=?, role=?, phone=?, center_id=? WHERE user_id=?",
                      (name, role, phone, center_id, target_id))
    conn.commit()
    _sync_staff_user_to_odoo(conn, target_id)
    raise Redirect("/admin/users")


@route("POST", r"/admin/users/(\d+)/toggle")
def admin_users_toggle(environ, m, conn, user):
    require_login(user, "admin")
    target_id = int(m.group(1))
    if target_id == user["user_id"]:
        raise Redirect("/admin/users")  # ห้ามระงับบัญชีตัวเอง
    conn.execute("UPDATE Users SET is_active = 1 - is_active WHERE user_id=?", (target_id,))
    conn.commit()
    raise Redirect("/admin/users")


@route("POST", r"/admin/users/(\d+)/delete")
def admin_users_delete(environ, m, conn, user):
    require_login(user, "admin")
    target_id = int(m.group(1))
    if target_id == user["user_id"]:
        raise Redirect("/admin/users")  # ห้ามลบบัญชีตัวเอง
    try:
        conn.execute("DELETE FROM Users WHERE user_id=?", (target_id,))
        conn.commit()
    except db.IntegrityError:
        conn.rollback()
        # มีข้อมูลผูกอยู่ (เช่น ช่างที่เคยรับงานซ่อม) -> ระงับการใช้งานแทนการลบ
        conn.execute("UPDATE Users SET is_active=0 WHERE user_id=?", (target_id,))
        conn.commit()
    raise Redirect("/admin/users")


@route("GET", r"/admin/centers")
def admin_centers(environ, m, conn, user):
    require_login(user, "admin")
    centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
    return render("admin_centers.html", centers=centers, user=user, error=None)


@route("POST", r"/admin/centers/new")
def admin_centers_new(environ, m, conn, user):
    require_login(user, "admin")
    fields, files = parse_multipart(environ)
    name = fields.get("name", "").strip()

    def with_error(msg):
        centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
        return render("admin_centers.html", centers=centers, user=user, error=msg)

    if not name:
        return with_error("กรุณากรอกชื่อศูนย์บริการ")

    lat_raw, lng_raw = fields.get("latitude", "").strip(), fields.get("longitude", "").strip()
    try:
        lat = float(lat_raw) if lat_raw else None
        lng = float(lng_raw) if lng_raw else None
    except ValueError:
        return with_error("พิกัด (ละติจูด/ลองจิจูด) ต้องเป็นตัวเลข")

    supports_fdm = 1 if fields.get("supports_fdm") else 0
    supports_resin = 1 if fields.get("supports_resin") else 0
    sells_products = 1 if fields.get("sells_products") else 0
    if not supports_fdm and not supports_resin and not sells_products:
        # อนุญาตให้ศูนย์ไม่รับซ่อมเลยได้ ถ้าเปิดขายสินค้าแทน (ศูนย์ขายอย่างเดียว ไม่ต้องรับซ่อม)
        # แต่ต้องทำอย่างน้อย 1 อย่าง (รับซ่อม หรือ ขายสินค้า) ไม่งั้นศูนย์นี้จะไม่มีประโยชน์อะไรเลย
        return with_error("กรุณาเลือกอย่างน้อย 1 อย่าง: รับซ่อม FDM/Resin หรือ เปิดขายสินค้า")

    tax_id = fields.get("tax_id", "").strip() or None
    email = fields.get("email", "").strip() or None
    website = fields.get("website", "").strip() or None
    is_headquarters = 1 if fields.get("is_headquarters") else 0
    bank_name = fields.get("bank_name", "").strip() or None
    bank_account_number = fields.get("bank_account_number", "").strip() or None

    cur = conn.execute(
        "INSERT INTO Service_Centers (name, address, phone, latitude, longitude, supports_fdm, supports_resin, "
        "sells_products, tax_id, email, website, is_headquarters, bank_name, bank_account_number) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, fields.get("address", ""), fields.get("phone", ""), lat, lng,
         supports_fdm, supports_resin, sells_products, tax_id, email, website, is_headquarters,
         bank_name, bank_account_number),
    )
    center_id = cur.lastrowid

    if is_headquarters:
        # มีสำนักงานใหญ่ได้สาขาเดียวในระบบ — ติ๊กสาขานี้แล้วถอดสถานะสาขาอื่นที่เคยตั้งไว้ออกอัตโนมัติ
        conn.execute("UPDATE Service_Centers SET is_headquarters=0 WHERE center_id != ?", (center_id,))

    logo_file = (files.get("logo") or [None])[0]
    cert_file = (files.get("cert_doc") or [None])[0]
    porpor_file = (files.get("por_por_20") or [None])[0]
    try:
        logo_stored = save_center_logo(center_id, logo_file)
        cert_stored = save_center_document(center_id, cert_file, "cert")
        porpor_stored = save_center_document(center_id, porpor_file, "porpor20")
    except ValueError as e:
        # ไฟล์แนบไม่ผ่านการตรวจสอบ -> ยกเลิกการสร้างศูนย์นี้ทั้งหมด กันมีศูนย์ครึ่งๆ กลางๆ ค้างในระบบ
        conn.rollback()
        return with_error(str(e))

    if logo_stored or cert_stored or porpor_stored:
        conn.execute(
            "UPDATE Service_Centers SET logo_filename=?, cert_doc_filename=?, por_por_20_filename=? WHERE center_id=?",
            (logo_stored, cert_stored, porpor_stored, center_id),
        )
    conn.commit()
    _sync_service_center_to_odoo(conn, center_id)
    raise Redirect("/admin/centers")


@route("POST", r"/admin/centers/(\d+)/edit")
def admin_centers_edit(environ, m, conn, user):
    require_login(user, "admin")
    center_id = int(m.group(1))
    fields, files = parse_multipart(environ)

    def with_error(msg):
        centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
        return render("admin_centers.html", centers=centers, user=user, error=msg)

    existing = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
    if not existing:
        raise HttpError(404, "ไม่พบศูนย์บริการนี้")

    name = fields.get("name", "").strip()
    if not name:
        return with_error("กรุณากรอกชื่อศูนย์บริการ")

    lat_raw, lng_raw = fields.get("latitude", "").strip(), fields.get("longitude", "").strip()
    try:
        lat = float(lat_raw) if lat_raw else None
        lng = float(lng_raw) if lng_raw else None
    except ValueError:
        return with_error("พิกัด (ละติจูด/ลองจิจูด) ต้องเป็นตัวเลข")

    supports_fdm = 1 if fields.get("supports_fdm") else 0
    supports_resin = 1 if fields.get("supports_resin") else 0
    sells_products = 1 if fields.get("sells_products") else 0
    if not supports_fdm and not supports_resin and not sells_products:
        return with_error("กรุณาเลือกอย่างน้อย 1 อย่าง: รับซ่อม FDM/Resin หรือ เปิดขายสินค้า")

    tax_id = fields.get("tax_id", "").strip() or None
    email = fields.get("email", "").strip() or None
    website = fields.get("website", "").strip() or None
    is_headquarters = 1 if fields.get("is_headquarters") else 0
    bank_name = fields.get("bank_name", "").strip() or None
    bank_account_number = fields.get("bank_account_number", "").strip() or None
    if is_headquarters:
        # มีสำนักงานใหญ่ได้สาขาเดียวในระบบ — ติ๊กสาขานี้แล้วถอดสถานะสาขาอื่นที่เคยตั้งไว้ออกอัตโนมัติ
        conn.execute("UPDATE Service_Centers SET is_headquarters=0 WHERE center_id != ?", (center_id,))

    # โลโก้/เอกสาร 3 ไฟล์ — ตรรกะเหมือนกันทั้ง 3: แนบไฟล์ใหม่มา -> ลบไฟล์เดิมทิ้งแล้วใช้ไฟล์ใหม่แทน,
    # ติ๊ก "ลบไฟล์นี้" โดยไม่แนบไฟล์ใหม่ -> ลบไฟล์เดิมทิ้งเฉยๆ (เหลือ NULL), ไม่ทำอะไรเลย -> คงไฟล์เดิมไว้
    logo_file = (files.get("logo") or [None])[0]
    cert_file = (files.get("cert_doc") or [None])[0]
    porpor_file = (files.get("por_por_20") or [None])[0]
    try:
        new_logo = save_center_logo(center_id, logo_file)
        new_cert = save_center_document(center_id, cert_file, "cert")
        new_porpor = save_center_document(center_id, porpor_file, "porpor20")
    except ValueError as e:
        return with_error(str(e))

    logo_filename = existing["logo_filename"]
    if new_logo:
        _delete_center_file(center_id, logo_filename)
        logo_filename = new_logo
    elif fields.get("remove_logo"):
        _delete_center_file(center_id, logo_filename)
        logo_filename = None

    cert_doc_filename = existing["cert_doc_filename"]
    if new_cert:
        _delete_center_file(center_id, cert_doc_filename)
        cert_doc_filename = new_cert
    elif fields.get("remove_cert_doc"):
        _delete_center_file(center_id, cert_doc_filename)
        cert_doc_filename = None

    por_por_20_filename = existing["por_por_20_filename"]
    if new_porpor:
        _delete_center_file(center_id, por_por_20_filename)
        por_por_20_filename = new_porpor
    elif fields.get("remove_por_por_20"):
        _delete_center_file(center_id, por_por_20_filename)
        por_por_20_filename = None

    conn.execute(
        """UPDATE Service_Centers SET name=?, address=?, phone=?, latitude=?, longitude=?,
                                       supports_fdm=?, supports_resin=?, sells_products=?, tax_id=?,
                                       email=?, website=?, is_headquarters=?, bank_name=?, bank_account_number=?,
                                       logo_filename=?, cert_doc_filename=?, por_por_20_filename=?
           WHERE center_id=?""",
        (name, fields.get("address", ""), fields.get("phone", ""), lat, lng,
         supports_fdm, supports_resin, sells_products, tax_id, email, website, is_headquarters,
         bank_name, bank_account_number,
         logo_filename, cert_doc_filename, por_por_20_filename, center_id),
    )
    conn.commit()
    _sync_service_center_to_odoo(conn, center_id)
    raise Redirect("/admin/centers")


@route("POST", r"/admin/centers/(\d+)/delete")
def admin_centers_delete(environ, m, conn, user):
    require_login(user, "admin")
    center_id = int(m.group(1))
    try:
        conn.execute("DELETE FROM Service_Centers WHERE center_id=?", (center_id,))
        conn.commit()
    except db.IntegrityError:
        conn.rollback()
        centers = annotate_centers(conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall())
        return render("admin_centers.html", centers=centers, user=user,
                       error="ลบไม่ได้ เนื่องจากมีผู้ใช้งานสังกัดศูนย์นี้อยู่ กรุณาย้ายผู้ใช้งานออกก่อน")
    raise Redirect("/admin/centers")


# --------------------------------------------- Maintenance Scheduler: admin config --
# แอดมินกำหนด/แก้ไข "แผนบำรุงรักษา" (งานที่ต้องทำเป็นระยะ + รอบวัน/ชั่วโมง) ที่นี่ — ระบบใช้คำนวณ
# รอบบำรุงรักษาอัตโนมัติให้ทุกเครื่อง (ดู _device_task_status) มีค่าเริ่มต้นให้แล้วตอนติดตั้งระบบ

@route("GET", r"/admin/maintenance-plans")
def admin_maintenance_plans(environ, m, conn, user):
    require_login(user, "admin")
    plans = conn.execute(
        "SELECT * FROM Maintenance_Plan_Items ORDER BY is_active DESC, device_type IS NULL, device_type, interval_type, interval_value"
    ).fetchall()
    return render("admin_maintenance_plans.html", plans=plans, user=user,
                   device_types=db.DEVICE_TYPES, interval_labels=db.MAINTENANCE_INTERVAL_TYPE_LABELS)


@route("POST", r"/admin/maintenance-plans/new")
def admin_maintenance_plans_new(environ, m, conn, user):
    require_login(user, "admin")
    form = parse_post(environ)
    task_name = form.get("task_name", "").strip()
    if not task_name:
        raise Redirect("/admin/maintenance-plans")
    device_type = form.get("device_type") or None
    if device_type not in db.DEVICE_TYPES:
        device_type = None
    interval_type = form.get("interval_type") if form.get("interval_type") in ("days", "hours") else "days"
    try:
        interval_value = int(form.get("interval_value") or 0)
    except ValueError:
        interval_value = 0
    if interval_value <= 0:
        raise Redirect("/admin/maintenance-plans")
    conn.execute(
        "INSERT INTO Maintenance_Plan_Items (device_type, task_name, interval_type, interval_value, is_active, created_at) "
        "VALUES (?,?,?,?,1,?)",
        (device_type, task_name, interval_type, interval_value, db.now()),
    )
    conn.commit()
    raise Redirect("/admin/maintenance-plans")


@route("POST", r"/admin/maintenance-plans/(\d+)/toggle")
def admin_maintenance_plans_toggle(environ, m, conn, user):
    require_login(user, "admin")
    plan_item_id = int(m.group(1))
    conn.execute(
        "UPDATE Maintenance_Plan_Items SET is_active = 1 - is_active WHERE plan_item_id=?", (plan_item_id,)
    )
    conn.commit()
    raise Redirect("/admin/maintenance-plans")


@route("POST", r"/admin/maintenance-plans/(\d+)/delete")
def admin_maintenance_plans_delete(environ, m, conn, user):
    require_login(user, "admin")
    plan_item_id = int(m.group(1))
    conn.execute("UPDATE Maintenance_Logs SET plan_item_id=NULL WHERE plan_item_id=?", (plan_item_id,))
    conn.execute("UPDATE Notifications SET plan_item_id=NULL WHERE plan_item_id=?", (plan_item_id,))
    conn.execute("DELETE FROM Maintenance_Plan_Items WHERE plan_item_id=?", (plan_item_id,))
    conn.commit()
    raise Redirect("/admin/maintenance-plans")


# ------------------------------------------------- Checklist: admin config --
# แอดมินกำหนด/แก้ไข "รายการตรวจสอบก่อนพิมพ์" ที่นี่ — บังคับติ๊กครบทุกข้อก่อนเริ่มงานพิมพ์ได้ทุกครั้ง

@route("GET", r"/admin/checklist-items")
def admin_checklist_items(environ, m, conn, user):
    require_login(user, "admin")
    items = conn.execute(
        "SELECT * FROM Checklist_Items ORDER BY is_active DESC, device_type IS NULL, device_type, sort_order"
    ).fetchall()
    return render("admin_checklist_items.html", items=items, user=user, device_types=db.DEVICE_TYPES)


@route("POST", r"/admin/checklist-items/new")
def admin_checklist_items_new(environ, m, conn, user):
    require_login(user, "admin")
    form = parse_post(environ)
    label = form.get("label", "").strip()
    if not label:
        raise Redirect("/admin/checklist-items")
    device_type = form.get("device_type") or None
    if device_type not in db.DEVICE_TYPES:
        device_type = None
    try:
        sort_order = int(form.get("sort_order") or 0)
    except ValueError:
        sort_order = 0
    conn.execute(
        "INSERT INTO Checklist_Items (device_type, label, sort_order, is_active, created_at) VALUES (?,?,?,1,?)",
        (device_type, label, sort_order, db.now()),
    )
    conn.commit()
    raise Redirect("/admin/checklist-items")


@route("POST", r"/admin/checklist-items/(\d+)/toggle")
def admin_checklist_items_toggle(environ, m, conn, user):
    require_login(user, "admin")
    checklist_item_id = int(m.group(1))
    conn.execute(
        "UPDATE Checklist_Items SET is_active = 1 - is_active WHERE checklist_item_id=?", (checklist_item_id,)
    )
    conn.commit()
    raise Redirect("/admin/checklist-items")


@route("POST", r"/admin/checklist-items/(\d+)/delete")
def admin_checklist_items_delete(environ, m, conn, user):
    require_login(user, "admin")
    checklist_item_id = int(m.group(1))
    conn.execute("DELETE FROM Checklist_Items WHERE checklist_item_id=?", (checklist_item_id,))
    conn.commit()
    raise Redirect("/admin/checklist-items")


# ----------------------------------------------------------- technician --

@route("GET", r"/tech/tasks")
def tech_tasks(environ, m, conn, user):
    require_login(user, "technician")
    tickets = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, sc.name AS center_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE t.assigned_tech_id=? AND t.status != 'Resolved/Closed'
           ORDER BY t.created_at""",
        (user["user_id"],),
    ).fetchall()
    return render("tech_tasks.html", tickets=tickets, user=user)


@route("GET", r"/tech/report")
def tech_report(environ, m, conn, user):
    """รายงานการทำงานส่วนตัวของช่าง — งานที่ทำ (แยกตามสถานะ พร้อมสัญลักษณ์) และอะไหล่ที่เบิกไป (รวมจำนวน)
    เลือกช่วงวันที่ได้ ค่าเริ่มต้นคือเดือนปัจจุบัน"""
    require_login(user, "technician")
    from_sql, to_sql, from_display, to_display = month_date_range(environ)

    # งานที่ทำ: นับตั๋วที่เริ่มงาน (created_at) หรือปิดงาน (closed_at) อยู่ในช่วงที่เลือก เพื่อให้เห็นทั้งงานที่
    # เพิ่งรับมอบหมายและงานที่เพิ่งปิดในช่วงนี้ แม้จะรับมอบหมายมาก่อนหน้าก็ตาม
    tickets = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, sc.name AS center_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE t.assigned_tech_id=?
             AND ((t.created_at BETWEEN ? AND ?) OR (t.closed_at BETWEEN ? AND ?))
           ORDER BY t.created_at DESC""",
        (user["user_id"], from_sql, to_sql, from_sql, to_sql),
    ).fetchall()
    status_counts = Counter(t["status"] for t in tickets)
    status_summary = [
        {"status": s, "label": db.STATUS_LABELS[s], "icon": db.STATUS_ICONS[s], "count": status_counts.get(s, 0)}
        for s in db.STATUSES
    ]
    resolved_count = status_counts.get("Resolved/Closed", 0)

    # อะไหล่ที่เบิกใช้: รวมจำนวนตามรหัสอะไหล่ ไม่นับรายการที่ถูกผู้จัดการปฏิเสธ (ไม่เคยตัดสต็อกจริง)
    parts_rows = conn.execute(
        """SELECT sl.part_sku_used AS sku, p.part_name, p.category, p.image_filename,
                  SUM(sl.quantity_used) AS total_qty, COUNT(*) AS times_used
           FROM Service_Logs sl
           JOIN Tickets t ON t.ticket_id = sl.ticket_id
           LEFT JOIN Spare_Parts p ON p.part_sku = sl.part_sku_used
           WHERE t.assigned_tech_id=? AND sl.part_sku_used IS NOT NULL AND sl.quantity_used > 0
                 AND sl.approval_status != 'rejected'
                 AND sl.created_at BETWEEN ? AND ?
           GROUP BY sl.part_sku_used, p.part_name, p.category, p.image_filename
           ORDER BY total_qty DESC""",
        (user["user_id"], from_sql, to_sql),
    ).fetchall()
    total_parts_qty = sum(r["total_qty"] for r in parts_rows)

    pending_count = conn.execute(
        """SELECT COUNT(*) AS n FROM Service_Logs sl JOIN Tickets t ON t.ticket_id = sl.ticket_id
           WHERE t.assigned_tech_id=? AND sl.approval_status='pending' AND sl.created_at BETWEEN ? AND ?""",
        (user["user_id"], from_sql, to_sql),
    ).fetchone()["n"]

    return render(
        "tech_report.html", user=user, tickets=tickets, status_summary=status_summary,
        resolved_count=resolved_count, parts_rows=parts_rows, total_parts_qty=total_parts_qty,
        pending_count=pending_count, date_from=from_display, date_to=to_display,
    )


@route("GET", r"/tech/ticket/(\d+)")
def tech_ticket_detail(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, d.type AS device_type, d.total_usage_hours AS device_total_usage_hours,
                  c.name AS customer_name, sc.name AS center_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["assigned_tech_id"] != user["user_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")
    # เบิกอะไหล่สำหรับงานซ่อม จำกัดให้ค้นหา/เลือกได้เฉพาะสินค้าหมวด "อะไหล่" เท่านั้น (ไม่รวม
    # เครื่องพิมพ์/วัสดุพิมพ์/อื่นๆ ที่ปนอยู่ในคลังเดียวกัน) เพราะรายการอะไหล่จริงมีจำนวนมาก
    parts = conn.execute(
        "SELECT * FROM Spare_Parts WHERE category='Spare_Part' ORDER BY part_name"
    ).fetchall()
    parts_for_js = [
        {
            "sku": p["part_sku"],
            "name": p["part_name"],
            "label": f"{p['part_name']} ({p['part_sku']})",
            "stock": p["stock_quantity"],
            "cost": p["cost_price"],
            "labor": p["labor_fee"],
        }
        for p in parts
    ]
    # ใช้หาชื่ออะไหล่ของประวัติเก่าที่อาจอ้างถึง SKU นอกหมวด "อะไหล่" (เช่น ก่อนมีการแบ่งหมวดสินค้า)
    part_name_lookup = {p["part_sku"]: p["part_name"] for p in conn.execute(
        "SELECT part_sku, part_name FROM Spare_Parts"
    ).fetchall()}
    logs = _service_logs_with_media(conn, ticket_id)
    media = conn.execute(
        "SELECT * FROM Ticket_Media WHERE ticket_id=? AND service_log_id IS NULL ORDER BY media_id", (ticket_id,)
    ).fetchall()
    quotes = get_quotes_for_ticket(conn, ticket_id)
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    payments = get_payments_for_ticket(conn, ticket_id)
    # แผนบำรุงรักษาที่ตรงกับประเภทเครื่องนี้ + ประวัติบำรุงรักษาล่าสุด — ให้ช่างบันทึกบำรุงรักษาได้จากหน้าซ่อมเลย
    maintenance_plan_items = _maintenance_plan_items_for_type(conn, t["device_type"])
    maintenance_logs = conn.execute(
        """SELECT ml.*, mpi.task_name FROM Maintenance_Logs ml
           LEFT JOIN Maintenance_Plan_Items mpi ON mpi.plan_item_id = ml.plan_item_id
           WHERE ml.device_sn=? ORDER BY ml.performed_at DESC, ml.maintenance_id DESC LIMIT 10""",
        (t["device_sn"],),
    ).fetchall()
    return render("tech_ticket_detail.html", t=t, parts=parts, parts_for_js=parts_for_js,
                   part_name_lookup=part_name_lookup, logs=logs, media=media, user=user,
                   quotes=quotes, invoice_items=invoice_items, invoice_total=invoice_total, payments=payments,
                   maintenance_plan_items=maintenance_plan_items, maintenance_logs=maintenance_logs,
                   interval_labels=db.MAINTENANCE_INTERVAL_TYPE_LABELS, today=db.now()[:10])


@route("POST", r"/tech/ticket/(\d+)/status")
def tech_ticket_status(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    existing = conn.execute(
        "SELECT status FROM Tickets WHERE ticket_id=? AND assigned_tech_id=?", (ticket_id, user["user_id"])
    ).fetchone()
    form = parse_post(environ)
    status = form.get("status")
    closed_at = db.now() if status == "Resolved/Closed" else None
    conn.execute("UPDATE Tickets SET status=?, closed_at=? WHERE ticket_id=? AND assigned_tech_id=?",
                 (status, closed_at, ticket_id, user["user_id"]))
    if existing and status != existing["status"]:
        _log_status_history(conn, ticket_id, existing["status"], status, user["user_id"])
    conn.commit()
    raise Redirect(f"/tech/ticket/{ticket_id}")


def _service_logs_with_media(conn, ticket_id):
    """ประวัติการบันทึกผลการซ่อม (Service_Logs) ของตั๋วนี้ พร้อมรูป/วิดีโอที่แนบมาแต่ละครั้ง (ถ้ามี) —
    แนบเป็น list ไว้ที่ key 'media' ของแต่ละแถว ใช้แสดงในหน้ารายละเอียดตั๋วทั้งฝั่งแอดมิน/ช่าง/ลูกค้า"""
    logs = conn.execute("SELECT * FROM Service_Logs WHERE ticket_id=? ORDER BY created_at", (ticket_id,)).fetchall()
    media_rows = conn.execute(
        "SELECT * FROM Ticket_Media WHERE ticket_id=? AND service_log_id IS NOT NULL ORDER BY media_id",
        (ticket_id,),
    ).fetchall()
    media_by_log = {}
    for md in media_rows:
        media_by_log.setdefault(md["service_log_id"], []).append(md)
    result = []
    for l in logs:
        l = dict(l)
        l["media"] = media_by_log.get(l["log_id"], [])
        result.append(l)
    return result


def _save_service_log_media(conn, ticket_id, service_log_id, images, video):
    """บันทึกไฟล์รูป/วิดีโอ (ผ่านการตรวจสอบแล้ว) ลง Ticket_Media ผูกกับรายการ Service_Logs ที่เพิ่งบันทึก
    (service_log_id) — ใช้ path/ชื่อไฟล์รูปแบบเดียวกับตอนแจ้งซ่อมครั้งแรก แต่เติม prefix "log<id>_" กันชื่อไฟล์ชนกัน
    ไม่ commit เอง ให้ผู้เรียกเป็นคน commit"""
    if not images and not video:
        return
    ticket_dir = os.path.join(UPLOADS_DIR, str(ticket_id))
    os.makedirs(ticket_dir, exist_ok=True)
    for idx, f in enumerate(images, start=1):
        stored = f"log{service_log_id}_img{idx}_{safe_filename(f['filename'])}"
        with open(os.path.join(ticket_dir, stored), "wb") as out:
            out.write(f["data"])
        conn.execute(
            "INSERT INTO Ticket_Media (ticket_id, media_type, filename, stored_name, uploaded_at, service_log_id) "
            "VALUES (?,?,?,?,?,?)",
            (ticket_id, "image", f["filename"], stored, db.now(), service_log_id),
        )
    if video:
        stored = f"log{service_log_id}_video_{safe_filename(video['filename'])}"
        with open(os.path.join(ticket_dir, stored), "wb") as out:
            out.write(video["data"])
        conn.execute(
            "INSERT INTO Ticket_Media (ticket_id, media_type, filename, stored_name, uploaded_at, service_log_id) "
            "VALUES (?,?,?,?,?,?)",
            (ticket_id, "video", video["filename"], stored, db.now(), service_log_id),
        )


@route("POST", r"/tech/ticket/(\d+)/log")
def tech_ticket_log(environ, m, conn, user):
    require_login(user, "admin", "technician")
    ticket_id = int(m.group(1))
    if user["role"] == "technician":
        owned = conn.execute(
            "SELECT ticket_id FROM Tickets WHERE ticket_id=? AND assigned_tech_id=?", (ticket_id, user["user_id"])
        ).fetchone()
        if not owned:
            raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")
    fields, files = parse_multipart(environ)
    images = files.get("images", [])
    videos = files.get("video", [])
    if len(images) > MAX_IMAGES:
        raise HttpError(400, f"อัปโหลดรูปภาพได้สูงสุด {MAX_IMAGES} รูป (เลือกมา {len(images)} รูป)")
    for f in images:
        if not f["content_type"].startswith("image/"):
            raise HttpError(400, f"ไฟล์ '{f['filename']}' ไม่ใช่ไฟล์รูปภาพที่รองรับ")
    if len(videos) > 1:
        raise HttpError(400, "อัปโหลดวิดีโอได้สูงสุด 1 คลิป")
    video = videos[0] if videos else None
    if video:
        if not video["content_type"].startswith("video/"):
            raise HttpError(400, f"ไฟล์ '{video['filename']}' ไม่ใช่ไฟล์วิดีโอที่รองรับ")
        if len(video["data"]) > MAX_VIDEO_BYTES:
            size_mb = round(len(video["data"]) / (1024 * 1024), 1)
            raise HttpError(400, f"ไฟล์วิดีโอขนาด {size_mb} MB เกินกำหนด (สูงสุด {MAX_VIDEO_MB} MB)")

    sku = fields.get("part_sku_used") or None
    qty = int(fields.get("quantity_used", 0) or 0)
    is_claim = 1 if fields.get("is_claim") else 0
    try:
        labor_fee = float(fields.get("labor_fee") or 0)
    except ValueError:
        labor_fee = 0
    approval_status = "auto"

    # เคลมประกัน — ไม่คิดค่าอะไหล่ ดังนั้นไม่ต้องส่งไปรออนุมัติจากมูลค่าอะไหล่ (มูลค่า = 0 บาทเสมอ)
    if sku and qty > 0 and not is_claim:
        part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
        cost = (part["cost_price"] if part else 0) * qty
        if cost > db.HIGH_COST_APPROVAL_THRESHOLD:
            approval_status = "pending"  # รอผู้จัดการอนุมัติก่อนตัดสต็อก

    cur = conn.execute(
        """INSERT INTO Service_Logs (ticket_id, part_sku_used, quantity_used, action_taken, tech_notes,
                                      labor_fee, is_claim, approval_status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (ticket_id, sku, qty, fields.get("action_taken", ""), fields.get("tech_notes", ""),
         labor_fee, is_claim, approval_status, db.now()),
    )
    log_id = cur.lastrowid

    if sku and qty > 0 and approval_status == "auto":
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?", (qty, sku))

    _save_service_log_media(conn, ticket_id, log_id, images, video)

    conn.commit()
    raise Redirect(f"/admin/ticket/{ticket_id}" if user["role"] == "admin" else f"/tech/ticket/{ticket_id}")


def _require_own_ticket_tech(conn, user, ticket_id):
    """ตรวจว่าตั๋วนี้มอบหมายให้ช่างคนที่ login อยู่จริง ใช้ก่อนแก้ไข/ยกเลิกประวัติการซ่อม"""
    ticket = conn.execute("SELECT assigned_tech_id FROM Tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not ticket or ticket["assigned_tech_id"] != user["user_id"]:
        raise HttpError(403, "คุณไม่มีสิทธิ์แก้ไขตั๋วซ่อมนี้")


@route("POST", r"/tech/ticket/(\d+)/log/(\d+)/edit")
def tech_ticket_log_edit(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id, log_id = int(m.group(1)), int(m.group(2))
    _require_own_ticket_tech(conn, user, ticket_id)
    log = conn.execute("SELECT * FROM Service_Logs WHERE log_id=? AND ticket_id=?", (log_id, ticket_id)).fetchone()
    if not log:
        raise HttpError(404, "ไม่พบประวัติการซ่อมนี้")

    form = parse_post(environ)
    new_sku = form.get("part_sku_used") or None
    new_is_claim = 1 if form.get("is_claim") else 0
    try:
        new_qty = int(form.get("quantity_used", 0) or 0)
    except ValueError:
        new_qty = 0
    try:
        new_labor = float(form.get("labor_fee") or 0)
    except ValueError:
        new_labor = 0

    # คืนสต็อกเดิมก่อน ถ้ารายการเดิมเคยตัดสต็อกไปแล้ว (auto หรือ approved) — แก้ไขแล้วจะคำนวณตัดสต็อกใหม่ทั้งหมด
    if log["part_sku_used"] and log["quantity_used"] and log["approval_status"] in ("auto", "approved"):
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
                     (log["quantity_used"], log["part_sku_used"]))

    # ประเมินสถานะอนุมัติใหม่จากค่าที่แก้ไขเสมอ ไม่ใช้สถานะอนุมัติเดิม (ค่าที่แก้อาจทำให้เกิน/ไม่เกินเกณฑ์ต่างไปจากเดิม)
    # เคลมประกัน — ไม่คิดค่าอะไหล่ ดังนั้นไม่ต้องส่งไปรออนุมัติจากมูลค่าอะไหล่ (มูลค่า = 0 บาทเสมอ)
    new_status = "auto"
    if new_sku and new_qty > 0 and not new_is_claim:
        part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (new_sku,)).fetchone()
        cost = (part["cost_price"] if part else 0) * new_qty
        if cost > db.HIGH_COST_APPROVAL_THRESHOLD:
            new_status = "pending"  # รอผู้จัดการอนุมัติใหม่อีกครั้ง

    conn.execute(
        """UPDATE Service_Logs SET part_sku_used=?, quantity_used=?, action_taken=?, tech_notes=?,
                                    labor_fee=?, is_claim=?, approval_status=? WHERE log_id=?""",
        (new_sku, new_qty, form.get("action_taken", ""), form.get("tech_notes", ""),
         new_labor, new_is_claim, new_status, log_id),
    )

    if new_sku and new_qty > 0 and new_status == "auto":
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?", (new_qty, new_sku))

    conn.commit()
    raise Redirect(f"/tech/ticket/{ticket_id}")


@route("POST", r"/tech/ticket/(\d+)/log/(\d+)/cancel")
def tech_ticket_log_cancel(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id, log_id = int(m.group(1)), int(m.group(2))
    _require_own_ticket_tech(conn, user, ticket_id)
    log = conn.execute("SELECT * FROM Service_Logs WHERE log_id=? AND ticket_id=?", (log_id, ticket_id)).fetchone()
    if not log:
        raise HttpError(404, "ไม่พบประวัติการซ่อมนี้")

    if log["part_sku_used"] and log["quantity_used"] and log["approval_status"] in ("auto", "approved"):
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
                     (log["quantity_used"], log["part_sku_used"]))

    conn.execute("DELETE FROM Service_Logs WHERE log_id=?", (log_id,))
    conn.commit()
    raise Redirect(f"/tech/ticket/{ticket_id}")


@route("POST", r"/tech/ticket/(\d+)/maintenance")
def tech_ticket_maintenance_log(environ, m, conn, user):
    """ให้ช่างบันทึกงานบำรุงรักษาที่ทำระหว่างเข้าซ่อมได้จากหน้าตั๋วซ่อมเลย ไม่ต้องแยกไปหน้า
    /device/<sn>/maintenance/log — ผูกกับ device_sn ของตั๋วนี้ ใช้คำนวณรอบบำรุงรักษาครั้งถัดไปเหมือนกัน"""
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT tk.device_sn, tk.assigned_tech_id, d.type AS device_type,
                  d.total_usage_hours AS device_total_usage_hours
           FROM Tickets tk JOIN Devices d ON d.device_sn = tk.device_sn WHERE tk.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["assigned_tech_id"] != user["user_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")

    form = parse_post(environ)
    plan_items = _maintenance_plan_items_for_type(conn, t["device_type"])
    # ติ๊กได้หลายงานพร้อมกัน (checkbox แยกตาม plan_item_id) — บันทึกครั้งเดียวสร้างประวัติแยกทีละงานที่ติ๊กไว้
    checked_plan_ids = [p["plan_item_id"] for p in plan_items if form.get(f"plan_{p['plan_item_id']}")]

    performed_at = form.get("performed_at") or db.now()[:10]
    hours_input = (form.get("hours_at_maintenance") or "").strip()
    if hours_input:
        try:
            hours_at_maintenance = float(hours_input)
        except ValueError:
            hours_at_maintenance = t["device_total_usage_hours"]  # กรอกไม่ถูกต้อง — ใช้ค่าสะสมปัจจุบันแทน
    else:
        hours_at_maintenance = t["device_total_usage_hours"]  # ไม่กรอก = ใช้ชั่วโมงสะสมปัจจุบันของเครื่อง

    parts_replaced = form.get("parts_replaced", "")
    notes = form.get("notes", "")

    if checked_plan_ids:
        for plan_item_id in checked_plan_ids:
            conn.execute(
                """INSERT INTO Maintenance_Logs (device_sn, plan_item_id, performed_at, hours_at_maintenance,
                                                  parts_replaced, notes, performed_by)
                   VALUES (?,?,?,?,?,?,?)""",
                (t["device_sn"], plan_item_id, performed_at, hours_at_maintenance, parts_replaced, notes, user["user_id"]),
            )
    else:
        # ไม่ได้ติ๊กงานไหนเลย — บันทึกอิสระไม่ผูกกับแผนงาน (plan_item_id = NULL) เหมือนเดิม
        conn.execute(
            """INSERT INTO Maintenance_Logs (device_sn, plan_item_id, performed_at, hours_at_maintenance,
                                              parts_replaced, notes, performed_by)
               VALUES (?,?,?,?,?,?,?)""",
            (t["device_sn"], None, performed_at, hours_at_maintenance, parts_replaced, notes, user["user_id"]),
        )
    conn.commit()
    raise Redirect(f"/tech/ticket/{ticket_id}")


def get_loggable_items(conn, ticket_id):
    """ประวัติการซ่อม (Service_Logs) ของตั๋วนี้ แปลงเป็นรายการที่พร้อมหยิบไปออกใบเสนอราคา"""
    logs = conn.execute(
        """SELECT sl.*, p.part_name, p.cost_price FROM Service_Logs sl
           LEFT JOIN Spare_Parts p ON p.part_sku = sl.part_sku_used
           WHERE sl.ticket_id=? ORDER BY sl.created_at""",
        (ticket_id,),
    ).fetchall()
    rows = []
    for l in logs:
        is_claim = bool(l["is_claim"]) if l["part_sku_used"] else False
        # เคลมประกัน — ไม่คิดค่าอะไหล่ (ราคาอะไหล่ = 0 บาทเสมอ) แต่ยังคงคิดค่าบริการตามปกติ
        part_cost = 0 if is_claim else ((l["cost_price"] or 0) * (l["quantity_used"] or 0) if l["part_sku_used"] else 0)
        labor = l["labor_fee"] or 0
        desc = l["action_taken"] or "งานซ่อม"
        if l["part_name"]:
            desc += f" ({l['part_name']} x{l['quantity_used']}{' — เคลม' if is_claim else ''})"
        rows.append({
            "log_id": l["log_id"], "created_at": l["created_at"], "description": desc,
            "suggested_price": round(part_cost + labor, 2), "tech_notes": l["tech_notes"], "is_claim": is_claim,
        })
    return rows


@route("GET", r"/tech/ticket/(\d+)/quote/new")
def tech_quote_form(environ, m, conn, user):
    """ออกใบเสนอราคาจากประวัติการซ่อม — เดิมทำได้เฉพาะช่างที่รับมอบหมายตั๋วนี้ ตอนนี้แอดมินก็สร้างได้ด้วย
    (ไม่ผูกกับ assigned_tech_id — แอดมินดูแลออกใบเสนอราคาแทนได้ทุกตั๋ว)"""
    require_login(user, "admin", "technician")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or (user["role"] == "technician" and t["assigned_tech_id"] != user["user_id"]):
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")
    loggable = get_loggable_items(conn, ticket_id)
    return render("tech_quote_form.html", t=t, loggable=loggable, user=user, error=None)


@route("POST", r"/tech/ticket/(\d+)/quote/new")
def tech_quote_submit(environ, m, conn, user):
    require_login(user, "admin", "technician")
    ticket_id = int(m.group(1))
    if user["role"] == "technician":
        t = conn.execute(
            """SELECT t.*, d.model, c.name AS customer_name FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.ticket_id=? AND t.assigned_tech_id=?""",
            (ticket_id, user["user_id"]),
        ).fetchone()
    else:
        t = conn.execute(
            """SELECT t.*, d.model, c.name AS customer_name FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.ticket_id=?""",
            (ticket_id,),
        ).fetchone()
    if not t:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")

    fields = parse_post(environ)
    loggable = get_loggable_items(conn, ticket_id)  # ที่มาของรายการต้องอ้างอิงจากประวัติจริงเท่านั้น ไม่รับข้อความจากฟอร์มตรงๆ

    items = []
    for row in loggable:
        if f"include_{row['log_id']}" not in fields:
            continue
        try:
            price = float(fields.get(f"price_{row['log_id']}") or 0)
        except ValueError:
            price = row["suggested_price"]
        items.append({"description": row["description"], "quantity": 1, "unit_price": price,
                       "tech_notes": row["tech_notes"]})

    if not items:
        return render("tech_quote_form.html", t=t, loggable=loggable, user=user,
                       error="กรุณาเลือกอย่างน้อย 1 รายการจากประวัติการซ่อม")

    cur = conn.execute(
        "INSERT INTO Quotations (ticket_id, created_by, created_at, notes) VALUES (?,?,?,?)",
        (ticket_id, user["user_id"], db.now(), fields.get("notes", "")),
    )
    quote_id = cur.lastrowid
    for it in items:
        conn.execute(
            "INSERT INTO Quotation_Items (quote_id, description, quantity, unit_price, tech_notes) VALUES (?,?,?,?,?)",
            (quote_id, it["description"], it["quantity"], it["unit_price"], it.get("tech_notes")),
        )
    conn.commit()
    raise Redirect(f"/admin/ticket/{ticket_id}" if user["role"] == "admin" else f"/tech/ticket/{ticket_id}")


# --------------------------------------------------------------- manager --

@route("GET", r"/manager/dashboard")
def manager_dashboard(environ, m, conn, user):
    require_login(user, "manager")
    return admin_dashboard(environ, m, conn, user)


@route("GET", r"/manager/approvals")
def manager_approvals(environ, m, conn, user):
    require_login(user, "manager")
    pending = conn.execute(
        """SELECT sl.*, p.part_name, p.cost_price, t.device_sn FROM Service_Logs sl
           JOIN Spare_Parts p ON p.part_sku = sl.part_sku_used
           JOIN Tickets t ON t.ticket_id = sl.ticket_id
           WHERE sl.approval_status='pending' AND t.center_id = ?
           ORDER BY sl.created_at""",
        (user.get("center_id"),),
    ).fetchall()
    return render("manager_approvals.html", pending=pending, user=user)


@route("POST", r"/manager/approvals/(\d+)/(approve|reject)")
def manager_approve(environ, m, conn, user):
    require_login(user, "manager")
    log_id, action = int(m.group(1)), m.group(2)
    log = conn.execute(
        """SELECT sl.*, t.center_id AS ticket_center_id FROM Service_Logs sl
           JOIN Tickets t ON t.ticket_id = sl.ticket_id WHERE sl.log_id=?""",
        (log_id,),
    ).fetchone()
    if log:
        require_center_access(user, log["ticket_center_id"])
    if log and log["approval_status"] == "pending":
        if action == "approve":
            conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?",
                         (log["quantity_used"], log["part_sku_used"]))
            conn.execute("UPDATE Service_Logs SET approval_status='approved' WHERE log_id=?", (log_id,))
        else:
            conn.execute("UPDATE Service_Logs SET approval_status='rejected' WHERE log_id=?", (log_id,))
        conn.commit()
    raise Redirect("/manager/approvals")


@route("GET", r"/manager/csat")
def manager_csat(environ, m, conn, user):
    require_login(user, "manager")
    rows = conn.execute(
        """SELECT t.ticket_id, t.csat_score, t.csat_comment, d.model, c.name AS customer_name
           FROM Tickets t JOIN Devices d ON d.device_sn=t.device_sn
           JOIN Customers c ON c.customer_id=d.customer_id
           WHERE t.csat_score IS NOT NULL AND t.center_id = ? ORDER BY t.closed_at DESC""",
        (user.get("center_id"),),
    ).fetchall()
    scores = [r["csat_score"] for r in rows if r["csat_score"] is not None]
    avg = round(sum(scores) / len(scores), 2) if scores else None
    return render("manager_csat.html", rows=rows, avg=avg, user=user)


# ----------------------------------------------------------------- sales --
# เฉพาะศูนย์บริการที่ sells_products=1 เท่านั้นที่บันทึกการขายได้ — sales/manager ถูกจำกัดให้เห็น
# เฉพาะศูนย์ที่ตัวเองสังกัด (เหมือน manager ในส่วนอื่นๆ), admin เห็น/เลือกได้ทุกศูนย์ที่ขายได้

# เอกสารยืนยันรับชำระเงินของบิลขายสินค้า — กดปุ่มใดปุ่มหนึ่งนี้ = ยืนยันยอดชำระเงินเข้าระบบ (ล็อกห้ามแก้ไข/ลบ
# รายการสินค้าในบิลอีกหลังจากนี้) "ใบเสนอราคา" ไม่ใช่เอกสารยืนยันรับชำระ จึงไม่อยู่ใน mapping นี้ พิมพ์ได้อิสระ
PAYMENT_DOC_TYPE_LABELS = {
    "cash_bill": "บิลเงินสด",
    "tax_invoice": "ใบกำกับภาษี",
}


def _customers_for_js(customers):
    """แปลงรายชื่อลูกค้าเป็นโครงสร้างสำหรับ JS ฝั่ง popup ค้นหาลูกค้า (พิมพ์ชื่อ/เบอร์โทร/เลขผู้เสียภาษีเพื่อค้นหา) —
    รูปแบบเดียวกับที่ใช้ในหน้าแจ้งซ่อมแทนลูกค้า (_staff_new_ticket_context) และหน้าจัดการลูกค้า"""
    return [
        {"id": c["customer_id"], "name": c["name"], "phone": c["phone"] or "", "tax_id": c["tax_id"] or ""}
        for c in customers
    ]


def _parts_for_js(parts):
    """แปลงรายการสินค้าเป็นโครงสร้างสำหรับ JS ฝั่งฟอร์มบันทึกการขาย (ค้นหา/autofill ราคา)
    label ต้องตรงกับ value ของ <option> ใน <datalist> ทุกตัวอักษร เพื่อให้ JS จับคู่สินค้าที่เลือกได้ถูกต้อง"""
    return [
        {
            "sku": p["part_sku"],
            "name": p["part_name"],
            "price": p["cost_price"],
            "stock": p["stock_quantity"],
            "label": f"{p['part_name']} ({p['part_sku']})",
        }
        for p in parts
    ]


def _parts_for_js_with_category(parts):
    """เหมือน _parts_for_js() แต่ label ต่อท้ายด้วยไอคอน+ชื่อประเภทสินค้า (เช่น "🔧 อะไหล่") — ใช้เฉพาะหน้าที่
    แอดมินเลือกสินค้าข้ามหลายศูนย์/หลายประเภทพร้อมกัน (สร้าง/แก้ไขคำสั่งซื้อจากศูนย์บริการ) เพื่อลดโอกาสเลือก
    สินค้าผิดชนิดที่ชื่อคล้ายกัน — ต้องตรงกับ value ของ <option> ใน <datalist> ทุกตัวอักษรเหมือน _parts_for_js()"""
    return [
        {
            "sku": p["part_sku"],
            "name": p["part_name"],
            "price": p["cost_price"],
            "stock": p["stock_quantity"],
            "label": f"{p['part_name']} ({p['part_sku']}) — "
                     f"{PRODUCT_CATEGORY_ICONS.get(p['category'], '📦')} {PRODUCT_CATEGORY_LABELS.get(p['category'], p['category'])}",
        }
        for p in parts
    ]


SALES_CHANNELS = ["หน้าร้าน", "Shopee", "Lazada", "Thaimart", "Facebook", "TikTok", "TDPrinter"]


@route("GET", r"/sales/new")
def sales_new_form(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    is_scoped = user["role"] in ("manager", "sales")
    selling_centers = conn.execute(
        "SELECT * FROM Service_Centers WHERE sells_products=1 ORDER BY name"
    ).fetchall()

    if is_scoped:
        scope_center = user.get("center_id")
        if not scope_center:
            return render("sales_new.html", user=user, error=None, blocked_reason="unassigned",
                           center=None, parts=[], parts_for_js=[], customers=[], selling_centers=[],
                           sales_channels=SALES_CHANNELS)
        center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (scope_center,)).fetchone()
        if not center or not center["sells_products"]:
            return render("sales_new.html", user=user, error=None, blocked_reason="not_selling",
                           center=center, parts=[], parts_for_js=[], customers=[], selling_centers=[],
                           sales_channels=SALES_CHANNELS)
    else:
        if not selling_centers:
            return render("sales_new.html", user=user, error=None, blocked_reason="none_selling",
                           center=None, parts=[], parts_for_js=[], customers=[], selling_centers=[],
                           sales_channels=SALES_CHANNELS)
        qs = parse_qs(environ.get("QUERY_STRING", ""))
        center_id_raw = qs.get("center_id", [""])[0]
        scope_center = int(center_id_raw) if center_id_raw else selling_centers[0]["center_id"]
        center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (scope_center,)).fetchone()
        if not center or not center["sells_products"]:
            return render("sales_new.html", user=user, error="ศูนย์บริการนี้ไม่ได้เปิดขายสินค้า",
                           center=None, parts=[], parts_for_js=[], customers=[], selling_centers=selling_centers,
                           sales_channels=SALES_CHANNELS)

    parts = _load_parts(conn, center_id=scope_center)
    customers = conn.execute("SELECT * FROM Customers ORDER BY name").fetchall()
    return render("sales_new.html", user=user, error=None, blocked_reason=None,
                   center=center, parts=parts, parts_for_js=_parts_for_js_with_category(parts),
                   customers=customers, customers_for_js=_customers_for_js(customers),
                   selling_centers=selling_centers, sales_channels=SALES_CHANNELS)


@route("POST", r"/sales/new")
def sales_new_submit(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    form = parse_post(environ)
    is_scoped = user["role"] in ("manager", "sales")

    if is_scoped:
        center_id = user.get("center_id")
        if not center_id:
            raise HttpError(403, "บัญชีนี้ยังไม่ได้ถูกกำหนดศูนย์บริการ")
    else:
        center_id_raw = form.get("center_id") or ""
        if not center_id_raw:
            raise HttpError(400, "กรุณาเลือกศูนย์บริการ")
        center_id = int(center_id_raw)

    center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
    if not center:
        raise HttpError(404, "ไม่พบศูนย์บริการนี้")
    require_center_access(user, center_id)
    if not center["sells_products"]:
        raise HttpError(403, "ศูนย์บริการนี้ไม่ได้เปิดขายสินค้า")

    parts = _load_parts(conn, center_id=center_id)
    parts_by_sku = {p["part_sku"]: p for p in parts}

    def with_error(msg):
        customers = conn.execute("SELECT * FROM Customers ORDER BY name").fetchall()
        selling_centers = conn.execute("SELECT * FROM Service_Centers WHERE sells_products=1 ORDER BY name").fetchall()
        return render("sales_new.html", user=user, error=msg, blocked_reason=None,
                       center=center, parts=parts, parts_for_js=_parts_for_js_with_category(parts),
                       customers=customers, customers_for_js=_customers_for_js(customers),
                       selling_centers=selling_centers, sales_channels=SALES_CHANNELS)

    # ฟอร์มส่งมาเป็นรายบรรทัด (เพิ่ม/ลบบรรทัดได้อิสระฝั่ง JS) — คีย์คือ sku_<idx>, qty_<idx>, price_<idx>
    # เก็บ index ทั้งหมดที่มีอยู่จริงในฟอร์ม แทนการวนตามรายการสินค้าทั้งคลังเหมือนเดิม
    line_indexes = sorted({
        key.split("_", 1)[1] for key in form if key.startswith("sku_") and form.get(key)
    })

    requested_qty = {}  # part_sku -> รวมจำนวนที่ขอขายทุกบรรทัดรวมกัน (กันเบิกเกินสต็อกเมื่อเลือกสินค้าเดียวกันหลายบรรทัด)
    line_items = []
    for idx in line_indexes:
        sku = (form.get(f"sku_{idx}") or "").strip()
        if not sku:
            continue
        part = parts_by_sku.get(sku)
        if not part:
            return with_error("มีสินค้าที่เลือกไม่ถูกต้อง หรือไม่ได้อยู่ในคลังของศูนย์นี้ กรุณาเลือกจากรายการค้นหาใหม่")

        qty_raw = (form.get(f"qty_{idx}") or "").strip()
        if not qty_raw:
            continue
        try:
            qty = int(float(qty_raw))
        except ValueError:
            return with_error(f"จำนวนของ '{part['part_name']}' ต้องเป็นตัวเลข")
        if qty <= 0:
            continue

        price_raw = (form.get(f"price_{idx}") or "").strip()
        try:
            unit_price = float(price_raw) if price_raw else part["cost_price"]
        except ValueError:
            return with_error(f"ราคาขายของ '{part['part_name']}' ต้องเป็นตัวเลข")

        requested_qty[sku] = requested_qty.get(sku, 0) + qty
        if requested_qty[sku] > part["stock_quantity"]:
            return with_error(
                f"สต็อก '{part['part_name']}' เหลือ {part['stock_quantity']} ไม่พอขายรวม {requested_qty[sku]} ชิ้น"
            )
        line_items.append((sku, qty, unit_price, part["commission_fee"]))

    if not line_items:
        return with_error("กรุณาเพิ่มอย่างน้อย 1 รายการสินค้า พร้อมเลือกสินค้าจากรายการค้นหาและระบุจำนวน")

    customer_id = form.get("customer_id") or None
    channel = (form.get("channel") or "").strip()
    if channel not in SALES_CHANNELS:
        channel = "หน้าร้าน"  # ไม่ได้เลือก/ค่าไม่ถูกต้อง — ถือว่าเป็นการขายหน้าร้านตามค่าเริ่มต้น

    cur = conn.execute(
        "INSERT INTO Sales_Orders (center_id, sold_by, customer_id, created_at, notes, channel) VALUES (?,?,?,?,?,?)",
        (center_id, user["user_id"], customer_id, db.now(), form.get("notes", ""), channel),
    )
    order_id = cur.lastrowid
    for sku, qty, unit_price, commission_fee in line_items:
        conn.execute(
            "INSERT INTO Sale_Items (order_id, part_sku, quantity, unit_price, commission_fee) VALUES (?,?,?,?,?)",
            (order_id, sku, qty, unit_price, commission_fee),
        )
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?", (qty, sku))
    conn.commit()
    raise Redirect(f"/sales/order/{order_id}")


@route("GET", r"/sales/orders")
def sales_orders(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    is_scoped = user["role"] in ("manager", "sales")
    from_sql, to_sql, from_display, to_display = month_date_range(environ)

    base_sql = """SELECT so.*, sc.name AS center_name, u.name AS sold_by_name, c.name AS customer_name,
             (SELECT COALESCE(SUM(si.quantity*si.unit_price),0) FROM Sale_Items si WHERE si.order_id=so.order_id) AS total_amount
           FROM Sales_Orders so
           JOIN Service_Centers sc ON sc.center_id = so.center_id
           JOIN Users u ON u.user_id = so.sold_by
           LEFT JOIN Customers c ON c.customer_id = so.customer_id
           WHERE so.created_at BETWEEN ? AND ?"""

    # ยอดขายแยกตามประเภทสินค้า/ยอดรวมรายเดือน ต้องไม่นับรายการที่ยกเลิกแล้วเสมอ ไม่ว่าจะดูจากสิทธิ์ไหน
    # (ไม่งั้นยอดขายรวมจะเพี้ยน) จึงกรอง cancelled_at IS NULL ในนี้แยกจากรายการที่แสดงในตาราง (ดูด้านล่าง)
    cat_sql = """SELECT p.category AS category,
             COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue,
             COALESCE(SUM(si.quantity), 0) AS qty
           FROM Sale_Items si
           JOIN Sales_Orders so ON so.order_id = si.order_id
           JOIN Spare_Parts p ON p.part_sku = si.part_sku
           WHERE so.created_at BETWEEN ? AND ? AND so.cancelled_at IS NULL"""

    if is_scoped:
        scope_center = user.get("center_id")
        if not scope_center:
            return render("sales_orders.html", user=user, orders=[], unassigned=True,
                           chart_labels=[], chart_values=[], category_summary=[],
                           date_from=from_display, date_to=to_display)
        # manager/sales ไม่เห็นรายการที่ถูกยกเลิกแล้วเลย (เฉพาะแอดมินเท่านั้นที่เห็น เพื่อตรวจสอบย้อนหลังได้)
        orders = conn.execute(
            base_sql + " AND so.center_id = ? AND so.cancelled_at IS NULL ORDER BY so.created_at DESC",
            (from_sql, to_sql, scope_center),
        ).fetchall()
        cat_rows = conn.execute(
            cat_sql + " AND so.center_id = ? GROUP BY p.category",
            (from_sql, to_sql, scope_center),
        ).fetchall()
    else:
        orders = conn.execute(base_sql + " ORDER BY so.created_at DESC", (from_sql, to_sql)).fetchall()
        cat_rows = conn.execute(cat_sql + " GROUP BY p.category", (from_sql, to_sql)).fetchall()

    cat_totals = {r["category"]: r for r in cat_rows}
    category_summary = [
        {
            "category": cat,
            "label": PRODUCT_CATEGORY_LABELS[cat],
            "icon": PRODUCT_CATEGORY_ICONS[cat],
            "color": PRODUCT_CATEGORY_COLORS[cat],
            "revenue": cat_totals[cat]["revenue"] if cat in cat_totals else 0,
            "qty": cat_totals[cat]["qty"] if cat in cat_totals else 0,
        }
        for cat in PRODUCT_CATEGORIES
    ]

    chart_labels, chart_values = monthly_revenue_series(orders)
    return render("sales_orders.html", user=user, orders=orders, unassigned=False,
                   chart_labels=chart_labels, chart_values=chart_values,
                   category_summary=category_summary, date_from=from_display, date_to=to_display)


def monthly_revenue_series(orders):
    """รวมยอดขาย (total_amount) ต่อเดือนจากรายการขาย — คืน (labels, values) เรียงตามเดือนจากเก่าไปใหม่
    ใช้ created_at (ข้อความรูปแบบ ISO YYYY-MM-DD...) ตัด 7 ตัวแรกเป็น YYYY-MM แทนการใช้ฟังก์ชันวันที่
    เฉพาะฐานข้อมูล เพื่อให้ทำงานเหมือนกันทั้ง SQLite (ตอนทดสอบ) และ MySQL (ตอนใช้งานจริง)"""
    totals = {}
    for o in orders:
        if o["cancelled_at"]:
            continue  # ไม่นับรายการที่ยกเลิกแล้วรวมในกราฟยอดขาย (แม้แอดมินจะเห็นแถวนี้ในตารางก็ตาม)
        month = (o["created_at"] or "")[:7]
        if not month:
            continue
        totals[month] = totals.get(month, 0) + (o["total_amount"] or 0)
    months = sorted(totals.keys())
    return months, [totals[m] for m in months]


def _sale_order_with_names(conn, order_id):
    """โหลดรายการขาย 1 บิล พร้อมชื่อศูนย์/พนักงานขาย/ลูกค้า/ผู้ยืนยันรับชำระ (ถ้ามี) — ใช้ร่วมกันทั้งหน้า
    รายละเอียดบิลและหน้าพิมพ์เอกสาร (บิลเงินสด/ใบกำกับภาษี/ใบเสนอราคา)"""
    return conn.execute(
        """SELECT so.*, sc.name AS center_name, u.name AS sold_by_name, c.name AS customer_name,
                  pc.name AS payment_confirmed_by_name, cb.name AS cancelled_by_name
           FROM Sales_Orders so
           JOIN Service_Centers sc ON sc.center_id = so.center_id
           JOIN Users u ON u.user_id = so.sold_by
           LEFT JOIN Customers c ON c.customer_id = so.customer_id
           LEFT JOIN Users pc ON pc.user_id = so.payment_confirmed_by
           LEFT JOIN Users cb ON cb.user_id = so.cancelled_by
           WHERE so.order_id=?""",
        (order_id,),
    ).fetchone()


@route("GET", r"/sales/order/(\d+)")
def sales_order_detail(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    order_id = int(m.group(1))
    order = _sale_order_with_names(conn, order_id)
    if not order:
        raise HttpError(404, "ไม่พบรายการขายนี้")
    require_center_access(user, order["center_id"])
    items = conn.execute(
        """SELECT si.*, sp.part_name FROM Sale_Items si
           JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
           WHERE si.order_id=?""",
        (order_id,),
    ).fetchall()
    total_amount = sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items)
    total_commission = sum((it["quantity"] or 0) * (it["commission_fee"] or 0) for it in items)
    return render("sales_order_detail.html", user=user, order=order, items=items,
                   total_amount=total_amount, total_commission=total_commission,
                   payment_doc_type_labels=PAYMENT_DOC_TYPE_LABELS)


def _get_sale_order_or_404(conn, order_id):
    order = conn.execute("SELECT * FROM Sales_Orders WHERE order_id=?", (order_id,)).fetchone()
    if not order:
        raise HttpError(404, "ไม่พบรายการขายนี้")
    return order


@route("POST", r"/sales/order/(\d+)/item/(\d+)/edit")
def sales_item_edit(environ, m, conn, user):
    """แก้ไขจำนวน/ราคาขายของรายการสินค้าแต่ละชิ้นในบิล — สินค้าที่ขายไปแล้วยังแก้ไขได้
    (สต็อกจะถูกปรับตามส่วนต่างจำนวนใหม่-เก่าโดยอัตโนมัติ)"""
    require_login(user, "admin", "manager", "sales")
    order_id, item_id = int(m.group(1)), int(m.group(2))
    order = _get_sale_order_or_404(conn, order_id)
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(400, "บิลนี้ถูกยกเลิกแล้ว แก้ไขรายการสินค้าไม่ได้")
    if order["payment_confirmed_at"]:
        raise HttpError(400, "บิลนี้ยืนยันรับชำระเงินแล้ว แก้ไขรายการสินค้าไม่ได้อีก")

    item = conn.execute("SELECT * FROM Sale_Items WHERE item_id=? AND order_id=?", (item_id, order_id)).fetchone()
    if not item:
        raise HttpError(404, "ไม่พบรายการสินค้านี้ในบิล")

    form = parse_post(environ)
    try:
        new_qty = int(form.get("quantity", ""))
        new_price = float(form.get("unit_price", ""))
    except ValueError:
        raise Redirect(f"/sales/order/{order_id}")
    if new_qty <= 0:
        raise Redirect(f"/sales/order/{order_id}")

    part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (item["part_sku"],)).fetchone()
    old_qty = item["quantity"] or 0
    delta = new_qty - old_qty  # จำนวนที่เปลี่ยนไปเทียบกับเดิม
    if delta > 0 and part and part["stock_quantity"] < delta:
        raise HttpError(400, f"สต็อก '{part['part_name']}' เหลือไม่พอ (เหลือ {part['stock_quantity']} ต้องการเพิ่มอีก {delta})")

    conn.execute("UPDATE Sale_Items SET quantity=?, unit_price=? WHERE item_id=?", (new_qty, new_price, item_id))
    if delta != 0:
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?",
                      (delta, item["part_sku"]))
    conn.commit()
    raise Redirect(f"/sales/order/{order_id}")


@route("POST", r"/sales/order/(\d+)/item/(\d+)/delete")
def sales_item_delete(environ, m, conn, user):
    """ลบรายการสินค้า 1 ชิ้นออกจากบิล — เฉพาะ admin/manager เท่านั้น (เซลลบเองไม่ได้)
    สต็อกของสินค้านั้นจะถูกคืนกลับให้อัตโนมัติ"""
    require_login(user, "admin", "manager")
    order_id, item_id = int(m.group(1)), int(m.group(2))
    order = _get_sale_order_or_404(conn, order_id)
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(400, "บิลนี้ถูกยกเลิกแล้ว ลบรายการสินค้าไม่ได้")
    if order["payment_confirmed_at"]:
        raise HttpError(400, "บิลนี้ยืนยันรับชำระเงินแล้ว ลบรายการสินค้าไม่ได้อีก")

    item = conn.execute("SELECT * FROM Sale_Items WHERE item_id=? AND order_id=?", (item_id, order_id)).fetchone()
    if not item:
        raise HttpError(404, "ไม่พบรายการสินค้านี้ในบิล")

    conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
                  (item["quantity"] or 0, item["part_sku"]))
    conn.execute("DELETE FROM Sale_Items WHERE item_id=?", (item_id,))
    conn.commit()
    raise Redirect(f"/sales/order/{order_id}")


@route("POST", r"/sales/order/(\d+)/delete")
def sales_order_delete(environ, m, conn, user):
    """ลบรายการขายทั้งบิล — เฉพาะ admin/manager เท่านั้น สต็อกของทุกชิ้นในบิลจะถูกคืนกลับให้อัตโนมัติ"""
    require_login(user, "admin", "manager")
    order_id = int(m.group(1))
    order = _get_sale_order_or_404(conn, order_id)
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(400, "บิลนี้ถูกยกเลิกแล้ว ลบทั้งบิลไม่ได้ (ใช้การยกเลิกไปแล้วแทน)")
    if order["payment_confirmed_at"]:
        raise HttpError(400, "บิลนี้ยืนยันรับชำระเงินแล้ว ลบทั้งบิลไม่ได้อีก")

    items = conn.execute("SELECT * FROM Sale_Items WHERE order_id=?", (order_id,)).fetchall()
    for it in items:
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
                      (it["quantity"] or 0, it["part_sku"]))
    conn.execute("DELETE FROM Sale_Items WHERE order_id=?", (order_id,))
    conn.execute("DELETE FROM Sales_Orders WHERE order_id=?", (order_id,))
    conn.commit()
    raise Redirect("/sales/orders")


@route("POST", r"/sales/order/(\d+)/cancel")
def sales_order_cancel(environ, m, conn, user):
    """ยกเลิกรายการขายทั้งบิล — เฉพาะแอดมินเท่านั้น (ต่างจากลบทั้งบิลที่ manager ทำได้ด้วย) ยกเลิกได้แม้ยืนยัน
    รับชำระเงินไปแล้ว เพื่อรองรับกรณีต้องยกเลิกบิลที่ปิดยอดไปแล้ว (เช่น ลูกค้าคืนสินค้า/บันทึกผิด) โดยยังเก็บ
    ประวัติทั้งบิลไว้ตรวจสอบย้อนหลังได้ (ต่างจากลบที่ลบทิ้งถาวร) — สต็อกของทุกชิ้นในบิลจะถูกคืนกลับให้อัตโนมัติ
    เหมือนตอนลบ — รายการที่ยกเลิกแล้วจะไม่แสดงในหน้ารายการขายของ manager/sales อีกต่อไป (แอดมินยังเห็นได้)"""
    require_login(user, "admin")
    order_id = int(m.group(1))
    order = _get_sale_order_or_404(conn, order_id)
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(400, "บิลนี้ถูกยกเลิกไปแล้ว")

    form = parse_post(environ)
    reason = form.get("cancel_reason", "").strip() or None

    items = conn.execute("SELECT * FROM Sale_Items WHERE order_id=?", (order_id,)).fetchall()
    for it in items:
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity + ? WHERE part_sku=?",
                      (it["quantity"] or 0, it["part_sku"]))
    conn.execute(
        "UPDATE Sales_Orders SET cancelled_at=?, cancelled_by=?, cancel_reason=? WHERE order_id=?",
        (db.now(), user["user_id"], reason, order_id),
    )
    conn.commit()
    raise Redirect(f"/sales/order/{order_id}")


@route("POST", r"/sales/order/(\d+)/confirm-payment")
def sales_order_confirm_payment(environ, m, conn, user):
    """ยืนยันรับชำระเงินเข้าระบบ — กดปุ่ม 'บิลเงินสด' หรือ 'ใบกำกับภาษี' บนหน้ารายละเอียดบิล คือการยืนยัน
    ยอดชำระเงินทั้งบิลนี้เข้าระบบ (ล็อกห้ามแก้ไข/ลบรายการสินค้าในบิลอีกหลังจากนี้ — ดูการ์ดใน sales_item_edit/
    sales_item_delete/sales_order_delete) แล้วพาไปหน้าพิมพ์เอกสารที่เลือก ใบกำกับภาษีออกได้เฉพาะบิลที่ผูก
    กับลูกค้าแล้วเท่านั้น ('ใบเสนอราคา' ไม่ใช่การยืนยันรับชำระ จึงพิมพ์ได้อิสระผ่าน sales_quote_print แยกต่างหาก
    ไม่ผ่าน route นี้) กดซ้ำ (เช่นเปิดสองแท็บ) จะไม่ยืนยันซ้ำ/เปลี่ยนประเภทเอกสาร แค่พาไปพิมพ์เอกสารเดิมที่ยืนยันไว้แล้ว"""
    require_login(user, "admin", "manager", "sales")
    order_id = int(m.group(1))
    order = _get_sale_order_or_404(conn, order_id)
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(400, "บิลนี้ถูกยกเลิกแล้ว ยืนยันรับชำระเงินไม่ได้")

    form = parse_post(environ)
    doc_type = form.get("doc_type", "")
    if doc_type not in PAYMENT_DOC_TYPE_LABELS:
        raise HttpError(400, "ประเภทเอกสารไม่ถูกต้อง")
    if doc_type == "tax_invoice" and not order["customer_id"]:
        raise HttpError(400, "ออกใบกำกับภาษีได้เฉพาะบิลที่เลือกลูกค้าแล้วเท่านั้น")

    if not order["payment_confirmed_at"]:
        conn.execute(
            "UPDATE Sales_Orders SET payment_confirmed_at=?, payment_confirmed_by=?, payment_doc_type=? WHERE order_id=?",
            (db.now(), user["user_id"], doc_type, order_id),
        )
        conn.commit()
        order = _get_sale_order_or_404(conn, order_id)

    doc_path = order["payment_doc_type"].replace("_", "-")  # 'cash_bill' -> 'cash-bill', 'tax_invoice' -> 'tax-invoice'
    raise Redirect(f"/sales/order/{order_id}/{doc_path}/print")


@route("GET", r"/sales/order/(\d+)/cash-bill/print")
def sales_cash_bill_print(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    order_id = int(m.group(1))
    order = _sale_order_with_names(conn, order_id)
    if not order:
        raise HttpError(404, "ไม่พบรายการขายนี้")
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(404, "บิลนี้ถูกยกเลิกแล้ว พิมพ์เอกสารนี้ไม่ได้")
    if order["payment_doc_type"] != "cash_bill" or not order["payment_confirmed_at"]:
        raise HttpError(404, "บิลนี้ยังไม่ได้ยืนยันรับชำระเงินเป็นบิลเงินสด ออกเอกสารนี้ไม่ได้")
    center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (order["center_id"],)).fetchone()
    customer = None
    if order["customer_id"]:
        customer = conn.execute("SELECT * FROM Customers WHERE customer_id=?", (order["customer_id"],)).fetchone()
    items = conn.execute(
        """SELECT si.*, sp.part_name FROM Sale_Items si
           JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
           WHERE si.order_id=?""",
        (order_id,),
    ).fetchall()
    # บิลเงินสด (ต่างจากใบกำกับภาษี) ไม่แยกคำนวณภาษีมูลค่าเพิ่ม — ยอดรวมทั้งหมด = รวมเป็นเงินตรงๆ
    subtotal = round(sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items), 2)
    hq = _get_hq_center(conn)
    return render("sales_cash_bill_print.html", order=order, center=center, customer=customer, items=items,
                   subtotal=subtotal, hq=hq)


@route("GET", r"/sales/order/(\d+)/tax-invoice/print")
def sales_tax_invoice_print(environ, m, conn, user):
    require_login(user, "admin", "manager", "sales")
    order_id = int(m.group(1))
    order = _sale_order_with_names(conn, order_id)
    if not order:
        raise HttpError(404, "ไม่พบรายการขายนี้")
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(404, "บิลนี้ถูกยกเลิกแล้ว พิมพ์เอกสารนี้ไม่ได้")
    if order["payment_doc_type"] != "tax_invoice" or not order["payment_confirmed_at"]:
        raise HttpError(404, "บิลนี้ยังไม่ได้ยืนยันรับชำระเงินเป็นใบกำกับภาษี ออกเอกสารนี้ไม่ได้")
    center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (order["center_id"],)).fetchone()
    customer = None
    if order["customer_id"]:
        customer = conn.execute("SELECT * FROM Customers WHERE customer_id=?", (order["customer_id"],)).fetchone()
    items = conn.execute(
        """SELECT si.*, sp.part_name FROM Sale_Items si
           JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
           WHERE si.order_id=?""",
        (order_id,),
    ).fetchall()
    subtotal = round(sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items), 2)
    vat = round(subtotal * db.VAT_RATE, 2)
    grand_total = round(subtotal + vat, 2)
    hq = _get_hq_center(conn)
    return render("sales_tax_invoice_print.html", order=order, center=center, customer=customer, items=items,
                   subtotal=subtotal, vat=vat, grand_total=grand_total,
                   vat_rate_percent=int(db.VAT_RATE * 100), hq=hq)


@route("GET", r"/sales/order/(\d+)/quote/print")
def sales_quote_print(environ, m, conn, user):
    """ใบเสนอราคา — เอกสารข้อมูลอย่างเดียว ไม่ใช่การยืนยันรับชำระเงิน ออกได้เฉพาะบิลที่เลือกลูกค้าแล้ว
    (ไม่ผูกกับสถานะ payment_confirmed_at เลย — พิมพ์ได้ไม่ว่าจะยืนยันรับชำระด้วยเอกสารอื่นไปแล้วหรือไม่ก็ตาม) —
    รองรับ checkbox "บิล VAT" บนหน้ารายละเอียดบิลขาย ส่งมาเป็น query string ?vat=1 (GET form, ไม่ต้องใช้ JS) —
    ถ้าไม่เลือก จะไม่คำนวณ/ไม่แสดงแถวภาษีมูลค่าเพิ่มในใบเสนอราคาเลย (ราคารวมทั้งหมด = รวมเป็นเงินตรงๆ)"""
    require_login(user, "admin", "manager", "sales")
    order_id = int(m.group(1))
    order = _sale_order_with_names(conn, order_id)
    if not order:
        raise HttpError(404, "ไม่พบรายการขายนี้")
    require_center_access(user, order["center_id"])
    if order["cancelled_at"]:
        raise HttpError(404, "บิลนี้ถูกยกเลิกแล้ว พิมพ์เอกสารนี้ไม่ได้")
    if not order["customer_id"]:
        raise HttpError(400, "ออกใบเสนอราคาได้เฉพาะบิลที่เลือกลูกค้าแล้วเท่านั้น")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    include_vat = qs.get("vat", [""])[0] == "1"
    center = conn.execute("SELECT * FROM Service_Centers WHERE center_id=?", (order["center_id"],)).fetchone()
    customer = conn.execute("SELECT * FROM Customers WHERE customer_id=?", (order["customer_id"],)).fetchone()
    items = conn.execute(
        """SELECT si.*, sp.part_name FROM Sale_Items si
           JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
           WHERE si.order_id=?""",
        (order_id,),
    ).fetchall()
    subtotal = round(sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items), 2)
    if include_vat:
        vat = round(subtotal * db.VAT_RATE, 2)
        grand_total = round(subtotal + vat, 2)
    else:
        vat = None
        grand_total = subtotal
    hq = _get_hq_center(conn)
    return render("sales_quote_print.html", order=order, center=center, customer=customer, items=items,
                   subtotal=subtotal, vat=vat, grand_total=grand_total, include_vat=include_vat,
                   vat_rate_percent=int(db.VAT_RATE * 100), hq=hq)


# --------------------------------------------------------------- reports --

@route("GET", r"/admin/reports")
def admin_reports(environ, m, conn, user):
    require_login(user, "admin", "manager")
    from_sql, to_sql, from_display, to_display = report_date_range(environ)
    is_manager = user["role"] == "manager"
    # manager ถูกจำกัดศูนย์ของตัวเองเสมอ — admin เลือกกรองศูนย์บริการเพิ่มเติมได้ผ่าน dropdown (?center_id=)
    # ไม่เลือก = ดูรวมทุกศูนย์เหมือนเดิม
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    selected_center_raw = qs.get("center_id", [""])[0].strip()
    selected_center_id = int(selected_center_raw) if selected_center_raw.isdigit() else None
    scope_center = user.get("center_id") if is_manager else selected_center_id
    all_centers = conn.execute("SELECT center_id, name FROM Service_Centers ORDER BY name").fetchall()
    # ใช้เป็นข้อมูลค้นหาศูนย์บริการแบบ popup ในฟอร์มกรองรายงาน (ศูนย์บริการอาจมีจำนวนมาก ไม่เหมาะกับ dropdown ยาวๆ)
    centers_for_js = [{"id": c["center_id"], "name": c["name"]} for c in all_centers]
    selected_center_name = next(
        (c["name"] for c in all_centers if c["center_id"] == selected_center_id), None
    ) if selected_center_id else None

    # รายงานรายการซ่อมแยกตามใบแจ้งหนี้ — ไม่ต้องแยกโค้ด scope_center/รวมทุกศูนย์เหมือนส่วนอื่นด้านล่าง
    # เพราะฟังก์ชันนี้รับ scope_center ตรงๆ (None = ดูรวมทุกศูนย์) จัดการเงื่อนไขให้ในตัวอยู่แล้ว
    repair_invoices = _repair_invoice_report_rows(conn, from_sql, to_sql, scope_center)
    ticket_reports = _ticket_report_rows(conn, from_sql, to_sql, scope_center)

    if scope_center:
        tech_rows = conn.execute(
            """SELECT u.user_id, u.name,
                 (SELECT COUNT(*) FROM Tickets t
                    WHERE t.assigned_tech_id = u.user_id AND t.created_at BETWEEN ? AND ?) AS assigned_count,
                 (SELECT COUNT(*) FROM Tickets t
                    WHERE t.assigned_tech_id = u.user_id AND t.status = 'Resolved/Closed'
                      AND t.closed_at BETWEEN ? AND ?) AS closed_count,
                 (SELECT COALESCE(SUM(sl.labor_fee), 0) FROM Service_Logs sl
                    JOIN Tickets t2 ON t2.ticket_id = sl.ticket_id
                    WHERE t2.assigned_tech_id = u.user_id AND sl.created_at BETWEEN ? AND ?) AS labor_total
               FROM Users u WHERE u.role = 'technician' AND u.is_active = 1 AND u.center_id = ?
               ORDER BY u.name""",
            (from_sql, to_sql, from_sql, to_sql, from_sql, to_sql, scope_center),
        ).fetchall()

        center_rows = conn.execute(
            """SELECT sc.center_id, sc.name,
                 COUNT(t.ticket_id) AS total_tickets,
                 SUM(CASE WHEN t.status = 'Resolved/Closed' THEN 1 ELSE 0 END) AS closed_tickets
               FROM Service_Centers sc
               LEFT JOIN Tickets t ON t.center_id = sc.center_id AND t.created_at BETWEEN ? AND ?
               WHERE sc.center_id = ?
               GROUP BY sc.center_id, sc.name
               ORDER BY sc.name""",
            (from_sql, to_sql, scope_center),
        ).fetchall()

        part_rows = conn.execute(
            """SELECT sp.part_sku, sp.part_name,
                 COALESCE(SUM(sl.quantity_used), 0) AS total_qty,
                 COALESCE(SUM(sl.quantity_used * sp.cost_price), 0) AS total_cost
               FROM Spare_Parts sp
               LEFT JOIN Service_Logs sl ON sl.part_sku_used = sp.part_sku AND sl.created_at BETWEEN ? AND ?
               WHERE sp.center_id = ? OR sp.center_id IS NULL
               GROUP BY sp.part_sku, sp.part_name
               ORDER BY total_qty DESC""",
            (from_sql, to_sql, scope_center),
        ).fetchall()

        total_tickets = conn.execute(
            "SELECT COUNT(*) c FROM Tickets WHERE created_at BETWEEN ? AND ? AND center_id = ?",
            (from_sql, to_sql, scope_center),
        ).fetchone()["c"]
        total_closed = conn.execute(
            "SELECT COUNT(*) c FROM Tickets WHERE status='Resolved/Closed' AND closed_at BETWEEN ? AND ? AND center_id = ?",
            (from_sql, to_sql, scope_center),
        ).fetchone()["c"]
        total_labor = conn.execute(
            """SELECT COALESCE(SUM(sl.labor_fee), 0) c FROM Service_Logs sl
               JOIN Tickets t ON t.ticket_id = sl.ticket_id
               WHERE sl.created_at BETWEEN ? AND ? AND t.center_id = ?""",
            (from_sql, to_sql, scope_center),
        ).fetchone()["c"]

        sales_rows = conn.execute(
            """SELECT u.user_id, u.name,
                 COUNT(DISTINCT so.order_id) AS order_count,
                 COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue,
                 COALESCE(SUM(si.quantity * si.commission_fee), 0) AS commission
               FROM Sales_Orders so
               JOIN Users u ON u.user_id = so.sold_by
               LEFT JOIN Sale_Items si ON si.order_id = so.order_id
               WHERE so.center_id = ? AND so.created_at BETWEEN ? AND ?
               GROUP BY u.user_id, u.name
               ORDER BY revenue DESC""",
            (scope_center, from_sql, to_sql),
        ).fetchall()
        total_sales_revenue = conn.execute(
            """SELECT COALESCE(SUM(si.quantity * si.unit_price), 0) c
               FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
               WHERE so.center_id = ? AND so.created_at BETWEEN ? AND ?""",
            (scope_center, from_sql, to_sql),
        ).fetchone()["c"]
        total_sales_commission = conn.execute(
            """SELECT COALESCE(SUM(si.quantity * si.commission_fee), 0) c
               FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
               WHERE so.center_id = ? AND so.created_at BETWEEN ? AND ?""",
            (scope_center, from_sql, to_sql),
        ).fetchone()["c"]

        center_sales_rows = conn.execute(
            """SELECT sc.center_id, sc.name,
                 COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue
               FROM Service_Centers sc
               LEFT JOIN Sales_Orders so ON so.center_id = sc.center_id AND so.created_at BETWEEN ? AND ?
               LEFT JOIN Sale_Items si ON si.order_id = so.order_id
               WHERE sc.center_id = ?
               GROUP BY sc.center_id, sc.name""",
            (from_sql, to_sql, scope_center),
        ).fetchall()

        # รายการดิบเบื้องหลังตัวเลขสรุป 6 การ์ดบนสุดของหน้ารายงาน — ใช้แสดง popup เมื่อคลิกที่การ์ด
        # (เหมือนรูปแบบเดียวกับการ์ดสถานะบน Dashboard) สโคปตามศูนย์บริการแบบเดียวกับตัวเลขสรุปด้านบนทุกประการ
        tickets_list_rows = conn.execute(
            """SELECT t.ticket_id, t.status, t.created_at, d.model, c.name AS customer_name
               FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.created_at BETWEEN ? AND ? AND t.center_id = ?
               ORDER BY t.created_at DESC""",
            (from_sql, to_sql, scope_center),
        ).fetchall()
        closed_list_rows = conn.execute(
            """SELECT t.ticket_id, t.closed_at, d.model, c.name AS customer_name
               FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.status='Resolved/Closed' AND t.closed_at BETWEEN ? AND ? AND t.center_id = ?
               ORDER BY t.closed_at DESC""",
            (from_sql, to_sql, scope_center),
        ).fetchall()
        labor_list_rows = conn.execute(
            """SELECT sl.ticket_id, sl.action_taken, sl.labor_fee, sl.created_at, d.model, u.name AS tech_name
               FROM Service_Logs sl
               JOIN Tickets t ON t.ticket_id = sl.ticket_id
               JOIN Devices d ON d.device_sn = t.device_sn
               LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
               WHERE sl.created_at BETWEEN ? AND ? AND sl.labor_fee > 0 AND t.center_id = ?
               ORDER BY sl.created_at DESC""",
            (from_sql, to_sql, scope_center),
        ).fetchall()
        parts_list_rows = conn.execute(
            """SELECT sl.ticket_id, sl.created_at, sl.quantity_used, sp.part_sku, sp.part_name,
                      (sl.quantity_used * sp.cost_price) AS line_cost, d.model
               FROM Service_Logs sl
               JOIN Spare_Parts sp ON sp.part_sku = sl.part_sku_used
               JOIN Tickets t ON t.ticket_id = sl.ticket_id
               JOIN Devices d ON d.device_sn = t.device_sn
               WHERE sl.created_at BETWEEN ? AND ? AND sl.part_sku_used IS NOT NULL AND sl.quantity_used > 0
                 AND (sp.center_id = ? OR sp.center_id IS NULL)
               ORDER BY sl.created_at DESC""",
            (from_sql, to_sql, scope_center),
        ).fetchall()
        sales_list_rows = conn.execute(
            """SELECT so.order_id, so.created_at, u.name AS sold_by_name, sp.part_name, si.quantity,
                      (si.quantity * si.unit_price) AS line_revenue,
                      (si.quantity * si.commission_fee) AS line_commission
               FROM Sale_Items si
               JOIN Sales_Orders so ON so.order_id = si.order_id
               JOIN Users u ON u.user_id = so.sold_by
               JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
               WHERE so.center_id = ? AND so.created_at BETWEEN ? AND ?
               ORDER BY so.created_at DESC""",
            (scope_center, from_sql, to_sql),
        ).fetchall()
    else:
        tech_rows = conn.execute(
            """SELECT u.user_id, u.name,
                 (SELECT COUNT(*) FROM Tickets t
                    WHERE t.assigned_tech_id = u.user_id AND t.created_at BETWEEN ? AND ?) AS assigned_count,
                 (SELECT COUNT(*) FROM Tickets t
                    WHERE t.assigned_tech_id = u.user_id AND t.status = 'Resolved/Closed'
                      AND t.closed_at BETWEEN ? AND ?) AS closed_count,
                 (SELECT COALESCE(SUM(sl.labor_fee), 0) FROM Service_Logs sl
                    JOIN Tickets t2 ON t2.ticket_id = sl.ticket_id
                    WHERE t2.assigned_tech_id = u.user_id AND sl.created_at BETWEEN ? AND ?) AS labor_total
               FROM Users u WHERE u.role = 'technician' AND u.is_active = 1
               ORDER BY u.name""",
            (from_sql, to_sql, from_sql, to_sql, from_sql, to_sql),
        ).fetchall()

        center_rows = conn.execute(
            """SELECT sc.center_id, sc.name,
                 COUNT(t.ticket_id) AS total_tickets,
                 SUM(CASE WHEN t.status = 'Resolved/Closed' THEN 1 ELSE 0 END) AS closed_tickets
               FROM Service_Centers sc
               LEFT JOIN Tickets t ON t.center_id = sc.center_id AND t.created_at BETWEEN ? AND ?
               GROUP BY sc.center_id, sc.name
               ORDER BY sc.name""",
            (from_sql, to_sql),
        ).fetchall()

        part_rows = conn.execute(
            """SELECT sp.part_sku, sp.part_name,
                 COALESCE(SUM(sl.quantity_used), 0) AS total_qty,
                 COALESCE(SUM(sl.quantity_used * sp.cost_price), 0) AS total_cost
               FROM Spare_Parts sp
               LEFT JOIN Service_Logs sl ON sl.part_sku_used = sp.part_sku AND sl.created_at BETWEEN ? AND ?
               GROUP BY sp.part_sku, sp.part_name
               ORDER BY total_qty DESC""",
            (from_sql, to_sql),
        ).fetchall()

        total_tickets = conn.execute(
            "SELECT COUNT(*) c FROM Tickets WHERE created_at BETWEEN ? AND ?", (from_sql, to_sql)
        ).fetchone()["c"]
        total_closed = conn.execute(
            "SELECT COUNT(*) c FROM Tickets WHERE status='Resolved/Closed' AND closed_at BETWEEN ? AND ?",
            (from_sql, to_sql),
        ).fetchone()["c"]
        total_labor = conn.execute(
            "SELECT COALESCE(SUM(labor_fee), 0) c FROM Service_Logs WHERE created_at BETWEEN ? AND ?",
            (from_sql, to_sql),
        ).fetchone()["c"]

        sales_rows = conn.execute(
            """SELECT u.user_id, u.name, sc.name AS center_name,
                 COUNT(DISTINCT so.order_id) AS order_count,
                 COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue,
                 COALESCE(SUM(si.quantity * si.commission_fee), 0) AS commission
               FROM Sales_Orders so
               JOIN Users u ON u.user_id = so.sold_by
               JOIN Service_Centers sc ON sc.center_id = so.center_id
               LEFT JOIN Sale_Items si ON si.order_id = so.order_id
               WHERE so.created_at BETWEEN ? AND ?
               GROUP BY u.user_id, u.name, sc.name
               ORDER BY revenue DESC""",
            (from_sql, to_sql),
        ).fetchall()
        total_sales_revenue = conn.execute(
            """SELECT COALESCE(SUM(si.quantity * si.unit_price), 0) c
               FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
               WHERE so.created_at BETWEEN ? AND ?""",
            (from_sql, to_sql),
        ).fetchone()["c"]
        total_sales_commission = conn.execute(
            """SELECT COALESCE(SUM(si.quantity * si.commission_fee), 0) c
               FROM Sale_Items si JOIN Sales_Orders so ON so.order_id = si.order_id
               WHERE so.created_at BETWEEN ? AND ?""",
            (from_sql, to_sql),
        ).fetchone()["c"]

        center_sales_rows = conn.execute(
            """SELECT sc.center_id, sc.name,
                 COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue
               FROM Service_Centers sc
               LEFT JOIN Sales_Orders so ON so.center_id = sc.center_id AND so.created_at BETWEEN ? AND ?
               LEFT JOIN Sale_Items si ON si.order_id = so.order_id
               GROUP BY sc.center_id, sc.name
               ORDER BY sc.name""",
            (from_sql, to_sql),
        ).fetchall()

        # รายการดิบเบื้องหลังตัวเลขสรุป 6 การ์ดบนสุดของหน้ารายงาน (ดูรายศูนย์บริการรวม — เหมือนด้านบนแต่ไม่กรองศูนย์)
        tickets_list_rows = conn.execute(
            """SELECT t.ticket_id, t.status, t.created_at, d.model, c.name AS customer_name
               FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.created_at BETWEEN ? AND ?
               ORDER BY t.created_at DESC""",
            (from_sql, to_sql),
        ).fetchall()
        closed_list_rows = conn.execute(
            """SELECT t.ticket_id, t.closed_at, d.model, c.name AS customer_name
               FROM Tickets t
               JOIN Devices d ON d.device_sn = t.device_sn
               JOIN Customers c ON c.customer_id = d.customer_id
               WHERE t.status='Resolved/Closed' AND t.closed_at BETWEEN ? AND ?
               ORDER BY t.closed_at DESC""",
            (from_sql, to_sql),
        ).fetchall()
        labor_list_rows = conn.execute(
            """SELECT sl.ticket_id, sl.action_taken, sl.labor_fee, sl.created_at, d.model, u.name AS tech_name
               FROM Service_Logs sl
               JOIN Tickets t ON t.ticket_id = sl.ticket_id
               JOIN Devices d ON d.device_sn = t.device_sn
               LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
               WHERE sl.created_at BETWEEN ? AND ? AND sl.labor_fee > 0
               ORDER BY sl.created_at DESC""",
            (from_sql, to_sql),
        ).fetchall()
        parts_list_rows = conn.execute(
            """SELECT sl.ticket_id, sl.created_at, sl.quantity_used, sp.part_sku, sp.part_name,
                      (sl.quantity_used * sp.cost_price) AS line_cost, d.model
               FROM Service_Logs sl
               JOIN Spare_Parts sp ON sp.part_sku = sl.part_sku_used
               JOIN Tickets t ON t.ticket_id = sl.ticket_id
               JOIN Devices d ON d.device_sn = t.device_sn
               WHERE sl.created_at BETWEEN ? AND ? AND sl.part_sku_used IS NOT NULL AND sl.quantity_used > 0
               ORDER BY sl.created_at DESC""",
            (from_sql, to_sql),
        ).fetchall()
        sales_list_rows = conn.execute(
            """SELECT so.order_id, so.created_at, u.name AS sold_by_name, sp.part_name, si.quantity,
                      (si.quantity * si.unit_price) AS line_revenue,
                      (si.quantity * si.commission_fee) AS line_commission
               FROM Sale_Items si
               JOIN Sales_Orders so ON so.order_id = si.order_id
               JOIN Users u ON u.user_id = so.sold_by
               JOIN Spare_Parts sp ON sp.part_sku = si.part_sku
               WHERE so.created_at BETWEEN ? AND ?
               ORDER BY so.created_at DESC""",
            (from_sql, to_sql),
        ).fetchall()

    total_parts_cost = sum(r["total_cost"] or 0 for r in part_rows)
    center_chart_labels = [r["name"] for r in center_sales_rows]
    center_chart_values = [r["revenue"] or 0 for r in center_sales_rows]

    # รายการตั๋ว/บันทึกค่าแรงเบื้องหลังตัวเลขของช่างแต่ละคน — ใช้แสดงใน popup เมื่อคลิกตัวเลขในตาราง
    # "ช่างซ่อม — จำนวนเคสและค่าแรง" (เคสที่ได้รับมอบหมาย / ปิดงานแล้ว / ค่าแรงรวม)
    tech_ids = [r["user_id"] for r in tech_rows]
    tech_cases = {tid: {"assigned": [], "closed": [], "labor": []} for tid in tech_ids}
    if tech_ids:
        placeholders = ",".join(["?"] * len(tech_ids))
        center_cond = " AND t.center_id = ?" if scope_center else ""
        center_params = [scope_center] if scope_center else []

        assigned_case_rows = conn.execute(
            f"""SELECT t.ticket_id, t.assigned_tech_id, d.model, t.status, t.created_at
                FROM Tickets t JOIN Devices d ON d.device_sn = t.device_sn
                WHERE t.assigned_tech_id IN ({placeholders}) AND t.created_at BETWEEN ? AND ?{center_cond}
                ORDER BY t.created_at DESC""",
            (*tech_ids, from_sql, to_sql, *center_params),
        ).fetchall()
        for r in assigned_case_rows:
            tech_cases[r["assigned_tech_id"]]["assigned"].append({
                "ticket_id": r["ticket_id"], "model": r["model"],
                "status": r["status"], "status_label": db.STATUS_LABELS.get(r["status"], r["status"]),
                "date": r["created_at"],
            })

        closed_case_rows = conn.execute(
            f"""SELECT t.ticket_id, t.assigned_tech_id, d.model, t.closed_at
                FROM Tickets t JOIN Devices d ON d.device_sn = t.device_sn
                WHERE t.assigned_tech_id IN ({placeholders}) AND t.status = 'Resolved/Closed'
                  AND t.closed_at BETWEEN ? AND ?{center_cond}
                ORDER BY t.closed_at DESC""",
            (*tech_ids, from_sql, to_sql, *center_params),
        ).fetchall()
        for r in closed_case_rows:
            tech_cases[r["assigned_tech_id"]]["closed"].append({
                "ticket_id": r["ticket_id"], "model": r["model"], "date": r["closed_at"],
            })

        labor_case_rows = conn.execute(
            f"""SELECT sl.ticket_id, t.assigned_tech_id, d.model, sl.action_taken, sl.labor_fee, sl.created_at
                FROM Service_Logs sl
                JOIN Tickets t ON t.ticket_id = sl.ticket_id
                JOIN Devices d ON d.device_sn = t.device_sn
                WHERE t.assigned_tech_id IN ({placeholders}) AND sl.labor_fee > 0
                  AND sl.created_at BETWEEN ? AND ?{center_cond}
                ORDER BY sl.created_at DESC""",
            (*tech_ids, from_sql, to_sql, *center_params),
        ).fetchall()
        for r in labor_case_rows:
            tech_cases[r["assigned_tech_id"]]["labor"].append({
                "ticket_id": r["ticket_id"], "model": r["model"],
                "action": r["action_taken"], "fee": r["labor_fee"] or 0, "date": r["created_at"],
            })

    # ข้อมูล popup ของการ์ดสรุป 6 ใบบนสุด (คลิกที่ตัวเลขบนการ์ดเพื่อดูรายการดิบที่ประกอบเป็นยอดนั้น)
    report_summary_for_js = {
        "tickets": [
            {"ticket_id": r["ticket_id"], "model": r["model"], "customer_name": r["customer_name"],
             "status_label": db.STATUS_LABELS.get(r["status"], r["status"]), "date": r["created_at"]}
            for r in tickets_list_rows
        ],
        "closed": [
            {"ticket_id": r["ticket_id"], "model": r["model"], "customer_name": r["customer_name"],
             "date": r["closed_at"]}
            for r in closed_list_rows
        ],
        "labor": [
            {"ticket_id": r["ticket_id"], "model": r["model"], "tech_name": r["tech_name"] or "-",
             "action": r["action_taken"] or "-", "fee": r["labor_fee"] or 0, "date": r["created_at"]}
            for r in labor_list_rows
        ],
        "parts": [
            {"ticket_id": r["ticket_id"], "model": r["model"], "part_sku": r["part_sku"],
             "part_name": r["part_name"], "qty": r["quantity_used"], "cost": r["line_cost"] or 0,
             "date": r["created_at"]}
            for r in parts_list_rows
        ],
        "sales": [
            {"order_id": r["order_id"], "sold_by": r["sold_by_name"], "part_name": r["part_name"],
             "qty": r["quantity"], "revenue": r["line_revenue"] or 0, "commission": r["line_commission"] or 0,
             "date": r["created_at"]}
            for r in sales_list_rows
        ],
    }

    return render(
        "admin_reports.html", user=user,
        from_display=from_display, to_display=to_display,
        tech_rows=tech_rows, center_rows=center_rows, part_rows=part_rows,
        total_tickets=total_tickets, total_closed=total_closed,
        total_labor=total_labor, total_parts_cost=total_parts_cost,
        sales_rows=sales_rows, total_sales_revenue=total_sales_revenue,
        total_sales_commission=total_sales_commission,
        center_chart_labels=center_chart_labels, center_chart_values=center_chart_values,
        all_centers=all_centers, selected_center_id=selected_center_id, is_manager=is_manager,
        tech_cases_for_js=tech_cases, report_summary_for_js=report_summary_for_js,
        centers_for_js=centers_for_js, selected_center_name=selected_center_name,
        repair_invoices=repair_invoices, ticket_reports=ticket_reports,
    )


@route("POST", r"/admin/reports/repair-invoice/(\d+)/recorded")
def admin_report_invoice_recorded(environ, m, conn, user):
    """ติ๊ก/ยกเลิกติ๊กว่าใบแจ้งหนี้นี้ลงบันทึกในบัญชี/ระบบภายนอกแล้วหรือยัง — กดจาก popup รายละเอียด
    ในหน้ารายงานรายการซ่อมแยกตามใบแจ้งหนี้ แล้วเด้งกลับไปหน้ารายงานเดิมพร้อมช่วงวันที่/ศูนย์ที่กรองไว้"""
    require_login(user, "admin", "manager")
    ticket_id = int(m.group(1))
    t = conn.execute("SELECT center_id FROM Tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        raise HttpError(404, "ไม่พบตั๋วนี้")
    require_center_access(user, t["center_id"])
    form = parse_post(environ)
    recorded = 1 if form.get("recorded") else 0
    if recorded:
        conn.execute(
            "UPDATE Tickets SET invoice_recorded=1, invoice_recorded_at=?, invoice_recorded_by=? WHERE ticket_id=?",
            (db.now(), user["user_id"], ticket_id),
        )
    else:
        conn.execute(
            "UPDATE Tickets SET invoice_recorded=0, invoice_recorded_at=NULL, invoice_recorded_by=NULL WHERE ticket_id=?",
            (ticket_id,),
        )
    conn.commit()
    from_display = (form.get("from") or "").strip()
    to_display = (form.get("to") or "").strip()
    center_id = (form.get("center_id") or "").strip()
    qs_parts = []
    if from_display:
        qs_parts.append(f"from={from_display}")
    if to_display:
        qs_parts.append(f"to={to_display}")
    if center_id:
        qs_parts.append(f"center_id={center_id}")
    qs = ("?" + "&".join(qs_parts)) if qs_parts else ""
    raise Redirect(f"/admin/reports{qs}")


# --------------------------------------------------- printable PDF views --
# หมายเหตุ: ไม่ใช้ไลบรารีสร้าง PDF ฝั่งเซิร์ฟเวอร์ (เช่น reportlab) เพราะเครื่องที่รันแอปนี้อาจไม่มีฟอนต์
# ที่รองรับภาษาไทย ทำให้ตัวอักษรไทยในไฟล์ PDF เพี้ยน/หาย แทนที่ด้วยหน้าเว็บที่จัดสำหรับพิมพ์โดยเฉพาะ
# แล้วใช้ปุ่ม "พิมพ์" ของเบราว์เซอร์ผู้ใช้ (Print -> Save as PDF) ซึ่งอ่านฟอนต์ไทยจากเครื่องผู้ใช้เองเสมอถูกต้อง

@route("GET", r"/quote/(\d+)/print")
def quote_print(environ, m, conn, user):
    quote_id = int(m.group(1))
    q = conn.execute("SELECT * FROM Quotations WHERE quote_id=?", (quote_id,)).fetchone()
    if not q:
        raise HttpError(404, "ไม่พบใบเสนอราคานี้")
    ticket_id = q["ticket_id"]
    if not user_can_view_ticket(conn, user, ticket_id):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงใบเสนอราคานี้")
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, c.phone, c.address, c.tax_id AS customer_tax_id FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    items = conn.execute(
        "SELECT * FROM Quotation_Items WHERE quote_id=? ORDER BY item_id", (quote_id,)
    ).fetchall()
    subtotal = round(sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items), 2)
    vat = round(subtotal * db.VAT_RATE, 2)
    grand_total = round(subtotal + vat, 2)
    creator = conn.execute("SELECT name FROM Users WHERE user_id=?", (q["created_by"],)).fetchone()
    hq = _get_hq_center(conn)
    return render("quote_print.html", q=q, t=t, items=items, subtotal=subtotal, vat=vat, grand_total=grand_total,
                   vat_rate_percent=int(db.VAT_RATE * 100), hq=hq,
                   creator_name=creator["name"] if creator else "-")


@route("POST", r"/quote/(\d+)/cancel")
def quote_cancel(environ, m, conn, user):
    """ยกเลิกใบเสนอราคา — ช่างทุกคน (ไม่จำกัดเฉพาะช่างที่รับผิดชอบตั๋วนั้น) รวมถึง admin/manager
    ลบได้ทั้งใบ (สำหรับ manager ยังคงจำกัดตามศูนย์บริการของตั๋วนั้นเหมือนสิทธิ์อื่นๆ)"""
    require_login(user, "admin", "manager", "technician")
    quote_id = int(m.group(1))
    q = conn.execute(
        """SELECT q.*, t.center_id AS ticket_center_id FROM Quotations q
           JOIN Tickets t ON t.ticket_id = q.ticket_id WHERE q.quote_id=?""",
        (quote_id,),
    ).fetchone()
    if not q:
        raise HttpError(404, "ไม่พบใบเสนอราคานี้")
    if user["role"] == "manager":
        require_center_access(user, q["ticket_center_id"])
    ticket_id = q["ticket_id"]
    conn.execute("DELETE FROM Quotation_Items WHERE quote_id=?", (quote_id,))
    conn.execute("DELETE FROM Quotations WHERE quote_id=?", (quote_id,))
    conn.commit()
    form = parse_post(environ)
    default_next = f"/admin/ticket/{ticket_id}" if user["role"] in ("admin", "manager") else f"/tech/ticket/{ticket_id}"
    raise Redirect(form.get("next") or default_next)


@route("GET", r"/ticket/(\d+)/invoice/print")
def invoice_print(environ, m, conn, user):
    ticket_id = int(m.group(1))
    if not user_can_view_ticket(conn, user, ticket_id):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงใบแจ้งหนี้นี้")
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, c.phone, c.address FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    return render("invoice_print.html", t=t, invoice_items=invoice_items, invoice_total=invoice_total)


def _ticket_for_pay(conn, ticket_id):
    return conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()


@route("GET", r"/ticket/(\d+)/pay")
def ticket_pay_form(environ, m, conn, user):
    ticket_id = int(m.group(1))
    if not user_can_view_ticket(conn, user, ticket_id):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงตั๋วซ่อมนี้")
    t = _ticket_for_pay(conn, ticket_id)
    if not t:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    payments = get_payments_for_ticket(conn, ticket_id)
    return render("ticket_pay.html", t=t, invoice_total=invoice_total, payments=payments,
                   user=user, error=None, max_slip_mb=MAX_SLIP_MB)


@route("POST", r"/ticket/(\d+)/pay")
def ticket_pay_submit(environ, m, conn, user):
    ticket_id = int(m.group(1))
    if not user_can_view_ticket(conn, user, ticket_id):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงตั๋วซ่อมนี้")
    t = _ticket_for_pay(conn, ticket_id)
    if not t:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")

    def with_error(msg):
        invoice_items, invoice_total = build_invoice(conn, ticket_id)
        payments = get_payments_for_ticket(conn, ticket_id)
        return render("ticket_pay.html", t=t, invoice_total=invoice_total, payments=payments,
                       user=user, error=msg, max_slip_mb=MAX_SLIP_MB)

    fields, files = parse_multipart(environ)
    slip_file = (files.get("slip") or [None])[0]
    try:
        amount = float(fields.get("amount") or 0)
    except ValueError:
        return with_error("จำนวนเงินไม่ถูกต้อง")
    if amount <= 0:
        return with_error("กรุณาระบุจำนวนเงินที่โอน")
    try:
        stored = save_payment_slip(ticket_id, slip_file)
    except ValueError as e:
        return with_error(str(e))

    conn.execute(
        """INSERT INTO Payments (ticket_id, amount, slip_filename, notified_by, status, created_at, notes)
           VALUES (?,?,?,?,'pending',?,?)""",
        (ticket_id, amount, stored, user["user_id"], db.now(), fields.get("notes", "")),
    )
    conn.commit()
    raise Redirect(f"/ticket/{ticket_id}/pay")


@route("POST", r"/ticket/(\d+)/payments/(\d+)/confirm")
def ticket_payment_confirm(environ, m, conn, user):
    ticket_id, payment_id = int(m.group(1)), int(m.group(2))
    _require_staff_can_manage_payment(conn, user, ticket_id)
    payment = conn.execute(
        "SELECT * FROM Payments WHERE payment_id=? AND ticket_id=?", (payment_id, ticket_id)
    ).fetchone()
    if not payment:
        raise HttpError(404, "ไม่พบรายการแจ้งชำระเงินนี้")
    conn.execute(
        "UPDATE Payments SET status='confirmed', confirmed_by=?, confirmed_at=? WHERE payment_id=?",
        (user["user_id"], db.now(), payment_id),
    )
    conn.commit()
    raise Redirect(_ticket_detail_url_for(user, ticket_id))


@route("POST", r"/ticket/(\d+)/payments/(\d+)/reject")
def ticket_payment_reject(environ, m, conn, user):
    ticket_id, payment_id = int(m.group(1)), int(m.group(2))
    _require_staff_can_manage_payment(conn, user, ticket_id)
    payment = conn.execute(
        "SELECT * FROM Payments WHERE payment_id=? AND ticket_id=?", (payment_id, ticket_id)
    ).fetchone()
    if not payment:
        raise HttpError(404, "ไม่พบรายการแจ้งชำระเงินนี้")
    conn.execute(
        "UPDATE Payments SET status='rejected', confirmed_by=?, confirmed_at=? WHERE payment_id=?",
        (user["user_id"], db.now(), payment_id),
    )
    conn.commit()
    raise Redirect(_ticket_detail_url_for(user, ticket_id))


@route("GET", r"/ticket/(\d+)/receipt/print")
def receipt_print(environ, m, conn, user):
    ticket_id = int(m.group(1))
    if not user_can_view_ticket(conn, user, ticket_id):
        raise HttpError(403, "ไม่มีสิทธิ์เข้าถึงใบเสร็จนี้")
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, c.phone, c.address FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    confirmed = [p for p in get_payments_for_ticket(conn, ticket_id) if p["status"] == "confirmed"]
    if not confirmed:
        raise HttpError(404, "ยังไม่มีการยืนยันการชำระเงินสำหรับตั๋วนี้ ออกใบเสร็จไม่ได้")
    total_paid = round(sum(p["amount"] or 0 for p in confirmed), 2)
    return render("receipt_print.html", t=t, invoice_items=invoice_items, invoice_total=invoice_total,
                   payments=confirmed, total_paid=total_paid)


# ------------------------------------------------------------- WSGI app --

def serve_static(path, environ, start_response):
    fs_path = os.path.join(STATIC_DIR, path.replace("/static/", "", 1))
    if not os.path.abspath(fs_path).startswith(os.path.abspath(STATIC_DIR)) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]
    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    # ไฟล์ที่อ้างอิงผ่าน asset_v() (style.css, sortable.js, ฯลฯ) จะมี ?v=<mtime> ต่อท้าย URL เสมอ — พอไฟล์เปลี่ยน
    # mtime เปลี่ยน URL ก็เปลี่ยนตาม จึงแคชยาวได้อย่างปลอดภัย ส่วนไฟล์ที่ยังไม่ได้ทำ cache-busting (เช่น รูปคู่มือ,
    # โลโก้ในเอกสารพิมพ์) ให้เบราว์เซอร์เช็กซ้ำทุกครั้งแทน กันปัญหาแคชเก่าค้างแบบที่เพิ่งเจอกับ style.css
    query = environ.get("QUERY_STRING", "")
    cache_control = "public, max-age=31536000, immutable" if "v=" in query else "no-cache"
    start_response("200 OK", [
        ("Content-Type", ctype or "application/octet-stream"),
        ("Cache-Control", cache_control),
    ])
    return [data]


MEDIA_RE = re.compile(r"^/media/(\d+)/(.+)$")


def serve_media(path, conn, user, start_response):
    """
    เสิร์ฟไฟล์รูป/วิดีโอที่ลูกค้าอัปโหลด — จำกัดสิทธิ์เข้าถึงเฉพาะ:
    เจ้าของตั๋ว (ลูกค้า), ช่างที่ได้รับมอบหมาย, admin, และ manager เท่านั้น
    """
    match = MEDIA_RE.match(path)
    if not match:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]
    ticket_id, filename = int(match.group(1)), match.group(2)

    row = conn.execute(
        """SELECT t.ticket_id, t.assigned_tech_id, d.customer_id FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()

    allowed = False
    if row and user:
        if user["role"] in ("admin", "manager"):
            allowed = True
        elif user["role"] == "technician" and row["assigned_tech_id"] == user["user_id"]:
            allowed = True
        elif user["role"] == "customer" and row["customer_id"] == user["customer_id"]:
            allowed = True

    if not row or not allowed:
        start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
        return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์นี้</p>".encode("utf-8")]

    fs_path = os.path.join(UPLOADS_DIR, str(ticket_id), filename)
    ticket_upload_dir = os.path.abspath(os.path.join(UPLOADS_DIR, str(ticket_id)))
    if not os.path.abspath(fs_path).startswith(ticket_upload_dir) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream"),
                               ("Content-Length", str(len(data)))])
    return [data]


DEVICE_PROOF_RE = re.compile(r"^/device-proof/(.+?)/([^/]+)$")


def serve_device_proof(path, conn, user, start_response):
    """เสิร์ฟไฟล์หลักฐานการสั่งซื้อเครื่องพิมพ์ — จำกัดสิทธิ์เข้าถึงเฉพาะเจ้าของเครื่อง (ลูกค้า)
    admin, manager, และช่างเท่านั้น (ข้อมูลนี้ผูกกับเครื่องพิมพ์ ไม่ใช่ตั๋วซ่อม จึงไม่จำกัดตามช่างที่ได้รับมอบหมาย)"""
    match = DEVICE_PROOF_RE.match(path)
    if not match:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]
    device_sn, filename = match.group(1), match.group(2)

    device = conn.execute(
        "SELECT device_sn, customer_id, purchase_proof_filename FROM Devices WHERE device_sn=?", (device_sn,)
    ).fetchone()

    allowed = False
    if device and user:
        if user["role"] in ("admin", "manager", "technician"):
            allowed = True
        elif user["role"] == "customer" and device["customer_id"] == user["customer_id"]:
            allowed = True

    if not device or not allowed or device["purchase_proof_filename"] != filename:
        start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
        return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์นี้</p>".encode("utf-8")]

    sn_dir = os.path.abspath(os.path.join(DEVICE_PROOF_DIR, safe_filename(device_sn)))
    fs_path = os.path.join(sn_dir, filename)
    if not os.path.abspath(fs_path).startswith(sn_dir) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream"),
                               ("Content-Length", str(len(data)))])
    return [data]


def serve_part_image(path, user, start_response):
    """เสิร์ฟรูปอะไหล่ — ไม่บังคับ login เพราะหน้าแรกสาธารณะ (home.html) ต้องแสดงรูปสินค้าให้ผู้เยี่ยมชม
    ที่ยังไม่ได้ login เห็นได้ด้วย (popup สอบถามสินค้า) — คลังอะไหล่จริง (category='Spare_Part')
    ก็ไม่ได้แสดงบนหน้าแรกอยู่แล้ว จึงไม่มีข้อมูลอ่อนไหวรั่วไหลจากการเปิดให้ดูรูปแบบไม่ต้อง login"""
    filename = path.replace("/part-image/", "", 1)
    fs_path = os.path.join(PART_IMAGES_DIR, filename)
    if not os.path.abspath(fs_path).startswith(os.path.abspath(PART_IMAGES_DIR)) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream"),
                               ("Content-Length", str(len(data)))])
    return [data]


def serve_center_logo(path, start_response):
    """เสิร์ฟโลโก้ศูนย์บริการ — ไม่บังคับ login เพราะแสดงบนหน้าแรกสาธารณะ (home.html) ด้วย"""
    filename = path.replace("/center-logo/", "", 1)
    center_dir = os.path.abspath(CENTER_FILES_DIR)
    fs_path = os.path.join(center_dir, filename)
    # filename มาจาก path จริง เช่น "3/logo_xxxx.png" (center_id/ชื่อไฟล์) — startswith กัน path traversal
    if not os.path.abspath(fs_path).startswith(center_dir) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream"),
                               ("Content-Length", str(len(data)))])
    return [data]


def serve_center_doc(path, user, start_response):
    """เสิร์ฟเอกสารประจำสาขา (หนังสือรับรอง/ภ.พ.20) — จำกัดสิทธิ์เฉพาะแอดมินเท่านั้น (เอกสารทางการของ
    บริษัท ไม่ใช่ข้อมูลที่ manager/ช่าง/เซลต้องใช้งาน)"""
    if not user or user["role"] != "admin":
        start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
        return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์นี้</p>".encode("utf-8")]

    filename = path.replace("/center-doc/", "", 1)
    center_dir = os.path.abspath(CENTER_FILES_DIR)
    fs_path = os.path.join(center_dir, filename)
    if not os.path.abspath(fs_path).startswith(center_dir) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream"),
                               ("Content-Length", str(len(data)))])
    return [data]


def serve_marketing_file(path, user, start_response):
    """เสิร์ฟไฟล์ทรัพยากรโปรโมท (โบรชัวร์/เอกสาร PDF) — จำกัดสิทธิ์เฉพาะผู้ใช้งานภายในที่ login แล้ว
    (แอดมิน/ผู้จัดการ/เซล) เท่านั้น ไม่เปิดสาธารณะเหมือนโลโก้สาขา เพราะเป็นสื่อโปรโมทสำหรับพาร์ทเนอร์ใช้งานเอง"""
    if not user or user["role"] not in ("admin", "manager", "sales"):
        start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
        return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์นี้</p>".encode("utf-8")]

    filename = path.replace("/resource-file/", "", 1)
    marketing_dir = os.path.abspath(MARKETING_DIR)
    fs_path = os.path.join(marketing_dir, filename)
    if not os.path.abspath(fs_path).startswith(marketing_dir) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream"),
                               ("Content-Length", str(len(data)))])
    return [data]


def serve_sharespace_file(path, conn, user, start_response):
    """เสิร์ฟไฟล์แนบกิจกรรม ShareSpace ทีละไฟล์ — ตรวจสิทธิ์ตามบทบาท+หมวดไฟล์ (marketing/technical) และ
    กิจกรรมต้องเผยแพร่แล้ว (status='published') เว้นแต่แอดมินซึ่งดูฉบับร่างได้ด้วย — ยกเว้นกิจกรรมที่เปิด
    is_public ไว้ (ลิงก์สาธารณะ /s/<id>) ซึ่งเข้าถึงได้โดยไม่ต้อง login เลย"""
    rest = path.replace("/sharespace-file/", "", 1)
    file_id_str = rest.split("/", 1)[0]
    if not file_id_str.isdigit():
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    f = conn.execute(
        """SELECT af.*, a.status AS activity_status, a.is_public AS activity_is_public,
                  a.download_deadline AS activity_download_deadline
           FROM Activity_Files af JOIN Activities a ON a.activity_id = af.activity_id WHERE af.file_id=?""",
        (int(file_id_str),),
    ).fetchone()
    if not f:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    publicly_ok = (
        f["activity_is_public"] and f["activity_status"] == "published"
        and not (f["activity_download_deadline"] and f["activity_download_deadline"] < db.now()[:10])
    )
    if not publicly_ok:
        if not user:
            start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
            return ["<h1>403</h1><p>กรุณาเข้าสู่ระบบ</p>".encode("utf-8")]
        if not _user_can_view_activity_category(user, f["category"]):
            start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
            return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์นี้</p>".encode("utf-8")]
        if f["activity_status"] != "published" and user["role"] != "admin":
            start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
            return ["<h1>403</h1><p>กิจกรรมนี้ยังไม่เผยแพร่</p>".encode("utf-8")]

    activity_dir = os.path.abspath(ACTIVITY_FILES_DIR)
    fs_path = os.path.join(activity_dir, f["stored_name"])
    if not os.path.abspath(fs_path).startswith(activity_dir) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as fh:
        data = fh.read()
    dl_name = (f["filename"] or "download").replace('"', "")
    start_response("200 OK", [
        ("Content-Type", ctype or "application/octet-stream"),
        ("Content-Length", str(len(data))),
        ("Content-Disposition", f'attachment; filename="{dl_name}"'),
    ])
    return [data]


def serve_sharespace_zip(path, conn, user, start_response):
    """รวมไฟล์แนบทั้งหมดในหมวดที่เลือกของกิจกรรมหนึ่ง เป็นไฟล์ ZIP เดียวแล้วดาวน์โหลด — ใช้กับปุ่ม
    "ดาวน์โหลดทั้งหมด" บนหน้า ShareSpace ตรวจสิทธิ์แบบเดียวกับการดาวน์โหลดไฟล์เดี่ยว — ยกเว้นกิจกรรมที่เปิด
    is_public ไว้ (ลิงก์สาธารณะ /s/<id>) ซึ่งเข้าถึงได้โดยไม่ต้อง login เลย"""
    rest = path.replace("/sharespace-zip/", "", 1).strip("/")
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in ("marketing", "technical"):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]
    activity_id, category = int(parts[0]), parts[1]

    activity = conn.execute("SELECT * FROM Activities WHERE activity_id=?", (activity_id,)).fetchone()
    if not activity:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    if not _activity_publicly_accessible(activity):
        if not user:
            start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
            return ["<h1>403</h1><p>กรุณาเข้าสู่ระบบ</p>".encode("utf-8")]
        if not _user_can_view_activity_category(user, category):
            start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
            return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์หมวดนี้</p>".encode("utf-8")]
        if activity["status"] != "published" and user["role"] != "admin":
            start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
            return ["<h1>403</h1><p>กิจกรรมนี้ยังไม่เผยแพร่</p>".encode("utf-8")]

    files = conn.execute(
        "SELECT * FROM Activity_Files WHERE activity_id=? AND category=?", (activity_id, category)
    ).fetchall()
    if not files:
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return ["ไม่มีไฟล์ในหมวดนี้".encode("utf-8")]

    activity_dir = os.path.abspath(ACTIVITY_FILES_DIR)
    buf = io.BytesIO()
    used_names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            fs_path = os.path.join(activity_dir, f["stored_name"])
            if not os.path.abspath(fs_path).startswith(activity_dir) or not os.path.isfile(fs_path):
                continue
            arcname = f["filename"] or f["stored_name"]
            # กันชื่อไฟล์ซ้ำกันใน zip เดียวกัน (คนละไฟล์แต่ตั้งชื่อต้นฉบับเหมือนกัน)
            n = 1
            base_name = arcname
            while arcname in used_names:
                stem, ext = os.path.splitext(base_name)
                arcname = f"{stem} ({n}){ext}"
                n += 1
            used_names.add(arcname)
            zf.write(fs_path, arcname=arcname)
    data = buf.getvalue()

    safe_title = safe_filename(activity["title"]) or f"activity-{activity_id}"
    zip_name = f"{safe_title}-{category}.zip"
    start_response("200 OK", [
        ("Content-Type", "application/zip"),
        ("Content-Length", str(len(data))),
        ("Content-Disposition", f'attachment; filename="{zip_name}"'),
    ])
    return [data]


def _extract_csrf_token(environ, raw_body):
    """ดึงค่า csrf_token จาก body ของ POST request โดยไม่ทำลาย wsgi.input เดิม
    (ใช้ตรวจสอบ CSRF ก่อนส่งต่อให้ route handler จัดการ body จริงอีกที)"""
    content_type = environ.get("CONTENT_TYPE", "")
    if "multipart/form-data" in content_type:
        fake_environ = dict(environ)
        fake_environ["wsgi.input"] = io.BytesIO(raw_body)
        fake_environ["CONTENT_LENGTH"] = str(len(raw_body))
        fields, _files = parse_multipart(fake_environ)
        return fields.get("csrf_token")
    try:
        fields = {k: v[0] for k, v in parse_qs(raw_body.decode("utf-8")).items()}
    except Exception:
        fields = {}
    return fields.get("csrf_token")


def _cookie_attrs(extra=""):
    attrs = "; SameSite=Lax"
    if COOKIE_SECURE:
        attrs += "; Secure"
    return attrs + extra


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    # แก้ปัญหา PATH_INFO เพี้ยน (mojibake) สำหรับ URL ที่มีอักษรไทย/ยูนิโค้ดหลายไบต์ เช่น รหัสสินค้า (SKU)
    # หรือ Serial Number ที่พิมพ์ผิดใส่อักษรไทยปนมา — ตามสเปก WSGI (PEP 3333) เซิร์ฟเวอร์ (wsgiref) จะ
    # unquote %XX ใน PATH_INFO ด้วย latin-1 เสมอ (ไม่ใช่ utf-8) ทำให้ไบต์ UTF-8 หลายไบต์ถูกตีความผิดเป็น
    # คนละตัวอักษร ต้อง encode กลับเป็น latin-1 bytes แล้ว decode เป็น utf-8 ใหม่ให้ตรงกับที่เก็บในฐานข้อมูลจริง
    try:
        path = path.encode("iso-8859-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass  # path ไม่ใช่ UTF-8 ที่ถูกต้อง (พบยาก) — ปล่อยผ่านตามเดิมแทนที่จะทำให้ request พัง
    method = environ.get("REQUEST_METHOD", "GET")

    if path.startswith("/static/"):
        return serve_static(path, environ, start_response)

    conn = db.get_conn()
    try:
        cookies = parse_cookies(environ)
        token = cookies.get("sid")
        user = get_current_user(environ, conn)
        sess = SESSIONS.get(token) if token else None
        _csrf_ctx.set(sess["csrf_token"] if sess else None)
        _notif_ctx.set(_unread_notification_count(conn, user) if user else 0)

        if path.startswith("/media/") and method == "GET":
            return serve_media(path, conn, user, start_response)

        if path.startswith("/part-image/") and method == "GET":
            return serve_part_image(path, user, start_response)

        if path.startswith("/device-proof/") and method == "GET":
            return serve_device_proof(path, conn, user, start_response)

        if path.startswith("/center-logo/") and method == "GET":
            return serve_center_logo(path, start_response)

        if path.startswith("/center-doc/") and method == "GET":
            return serve_center_doc(path, user, start_response)

        if path.startswith("/resource-file/") and method == "GET":
            return serve_marketing_file(path, user, start_response)

        if path.startswith("/sharespace-file/") and method == "GET":
            return serve_sharespace_file(path, conn, user, start_response)

        if path.startswith("/sharespace-zip/") and method == "GET":
            return serve_sharespace_zip(path, conn, user, start_response)

        if method == "POST":
            # อ่าน body ครั้งเดียวมาบัฟเฟอร์ไว้ใน memory แล้วค่อยยัดกลับเข้า wsgi.input ให้
            # route handler อ่านต่อได้ตามปกติ (ต้องอ่านก่อนเพื่อตรวจ CSRF token ในนั้น)
            try:
                length = int(environ.get("CONTENT_LENGTH", 0) or 0)
            except ValueError:
                length = 0
            raw_body = environ["wsgi.input"].read(length) if length else b""
            environ["wsgi.input"] = io.BytesIO(raw_body)
            environ["CONTENT_LENGTH"] = str(len(raw_body))

            if path != "/login" and user is not None:
                submitted = _extract_csrf_token(environ, raw_body) or ""
                expected = sess["csrf_token"] if sess else None
                if not expected or not hmac.compare_digest(submitted, expected):
                    start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
                    return [("<h1>403</h1><p>คำขอไม่ถูกต้องหรือหมดอายุ (CSRF token ไม่ตรงกัน) "
                             "กรุณาโหลดหน้าใหม่แล้วลองส่งฟอร์มอีกครั้ง</p>"
                             "<a href='/'>กลับหน้าแรก</a>").encode("utf-8")]

        for m_method, regex, handler in ROUTES:
            if m_method != method:
                continue
            match = regex.match(path)
            if match:
                try:
                    body = handler(environ, match, conn, user)
                except Redirect as r:
                    loc = r.location
                    headers = [("Location", "")]
                    set_cookie = None
                    if "::SETCOOKIE::" in loc:
                        loc, new_token = loc.split("::SETCOOKIE::")
                        set_cookie = f"sid={new_token}; Path=/; HttpOnly" + _cookie_attrs()
                    elif "::CLEARCOOKIE::" in loc:
                        loc = loc.replace("::CLEARCOOKIE::", "")
                        set_cookie = "sid=; Path=/; Max-Age=0; HttpOnly" + _cookie_attrs()
                    headers[0] = ("Location", loc)
                    if set_cookie:
                        headers.append(("Set-Cookie", set_cookie))
                    start_response("302 Found", headers)
                    return [b""]
                except HttpError as e:
                    start_response(f"{e.status} Error", [("Content-Type", "text/html; charset=utf-8")])
                    return [f"<h1>{e.status}</h1><p>{e.message}</p><a href='/'>กลับหน้าแรก</a>".encode("utf-8")]
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
                return [body]
        start_response("404 Not Found", [("Content-Type", "text/html; charset=utf-8")])
        return [b"<h1>404</h1><p>\xe0\xb9\x84\xe0\xb8\xa1\xe0\xb9\x88\xe0\xb8\x9e\xe0\xb8\x9a\xe0\xb8\xab\xe0\xb8\x99\xe0\xb9\x89\xe0\xb8\xb2\xe0\xb8\x99\xe0\xb8\xb5\xe0\xb9\x89</p>"]
    finally:
        conn.close()


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """wsgiref's default server handles one request at a time; this lets it
    serve several concurrent requests (e.g. multiple staff/customers at
    once) using stdlib only — no extra dependency needed for Docker use."""
    daemon_threads = True


class QuietWSGIRequestHandler(WSGIRequestHandler):
    """Log to stdout in a container-friendly single-line format."""

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.address_string(), fmt % args))


def _wait_for_db(max_attempts=30, delay_seconds=2):
    """รอให้ PostgreSQL พร้อมรับการเชื่อมต่อก่อน — กันเคส container ของแอปเริ่มไวกว่า
    PostgreSQL (เช่นตอน `docker compose up` ครั้งแรกที่ยังไม่มี healthcheck ผ่าน) —
    เชื่อมต่อไปที่ฐานข้อมูล maintenance 'postgres' เท่านั้น (ไม่ใช่ฐานข้อมูลเป้าหมาย PG_DATABASE
    ซึ่งอาจยังไม่ถูกสร้างในตอนนี้) แค่เช็คว่า server รับการเชื่อมต่อได้แล้วหรือยัง"""
    import psycopg2
    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg2.connect(
                host=db.PG_HOST, port=db.PG_PORT,
                user=db.PG_USER, password=db.PG_PASSWORD,
                dbname="postgres", connect_timeout=3,
            )
            conn.close()
            return
        except Exception as exc:
            print(f"[startup] รอ PostgreSQL ({db.PG_HOST}:{db.PG_PORT}) ... "
                  f"ครั้งที่ {attempt}/{max_attempts} ({exc})")
            time.sleep(delay_seconds)
    raise RuntimeError(f"เชื่อมต่อ PostgreSQL ที่ {db.PG_HOST}:{db.PG_PORT} ไม่สำเร็จหลังจากลอง {max_attempts} ครั้ง")


if __name__ == "__main__":
    _wait_for_db()
    db.init_db()
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(PART_IMAGES_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 8000))
    print(f"Repair Ticketing System running on http://0.0.0.0:{port}")
    with make_server(
        "0.0.0.0", port, application,
        server_class=ThreadingWSGIServer,
        handler_class=QuietWSGIRequestHandler,
    ) as httpd:
        httpd.serve_forever()
