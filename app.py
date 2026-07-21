# -*- coding: utf-8 -*-
"""
ระบบบริหารจัดการงานซ่อม (Repair Ticketing System) — prototype
รันด้วย Python มาตรฐาน (wsgiref) + SQLite + Jinja2 เท่านั้น ไม่ต้องพึ่ง framework ภายนอก
ใช้งาน:   python app.py   แล้วเปิด http://localhost:8000
"""
import os
import re
import uuid
import sqlite3
import mimetypes
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse
from wsgiref.simple_server import make_server

from jinja2 import Environment, FileSystemLoader, select_autoescape

import db

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
PART_IMAGES_DIR = os.path.join(UPLOADS_DIR, "parts")

MAX_IMAGES = 10
MAX_VIDEO_MB = 10
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024
MAX_PART_IMAGE_MB = 5
MAX_PART_IMAGE_BYTES = MAX_PART_IMAGE_MB * 1024 * 1024

env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html"]),
)

# session_token -> user_id  (in-memory: รีสตาร์ทเซิร์ฟเวอร์แล้วต้อง login ใหม่)
SESSIONS = {}

ROLE_HOME = {
    "customer": "/customer/tickets",
    "admin": "/admin/dashboard",
    "technician": "/tech/tasks",
    "manager": "/manager/dashboard",
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
    html = tmpl.render(statuses=db.STATUSES, **ctx)
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


def get_current_user(environ, conn):
    cookies = parse_cookies(environ)
    token = cookies.get("sid")
    user_id = SESSIONS.get(token)
    if not user_id:
        return None
    row = conn.execute("SELECT * FROM Users WHERE user_id=?", (user_id,)).fetchone()
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
        part_cost = (r["cost_price"] or 0) * (r["quantity_used"] or 0) if r["part_sku_used"] else 0
        labor = r["labor_fee"] or 0
        line_total = part_cost + labor
        total += line_total
        items.append({
            "created_at": r["created_at"], "action": r["action_taken"] or "-",
            "part_name": r["part_name"], "part_cost": part_cost,
            "labor_fee": labor, "line_total": line_total,
        })
    return items, round(total, 2)


def user_can_view_ticket(conn, user, ticket_id):
    """ใครมีสิทธิ์ดูตั๋วนี้บ้าง: เจ้าของ(ลูกค้า), ช่างที่ได้รับมอบหมาย, admin, manager"""
    if not user:
        return False
    row = conn.execute(
        """SELECT t.assigned_tech_id, d.customer_id FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not row:
        return False
    if user["role"] in ("admin", "manager"):
        return True
    if user["role"] == "technician" and row["assigned_tech_id"] == user["user_id"]:
        return True
    if user["role"] == "customer" and row["customer_id"] == user["customer_id"]:
        return True
    return False


def days_left(warranty_end_date):
    import datetime
    try:
        end = datetime.datetime.strptime(warranty_end_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (end - datetime.date.today()).days


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
    raise Redirect("/login")


@route("GET", r"/login")
def login_form(environ, m, conn, user):
    if user:
        raise Redirect(ROLE_HOME[user["role"]])
    return render("login.html", error=None)


@route("POST", r"/login")
def login_submit(environ, m, conn, user):
    form = parse_post(environ)
    username = form.get("username", "").strip()
    password = form.get("password", "")
    row = conn.execute(
        "SELECT * FROM Users WHERE username=? AND password=?",
        (username, db.hash_password(password)),
    ).fetchone()
    if not row:
        return render("login.html", error="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    if not row["is_active"]:
        return render("login.html", error="บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อแอดมิน")
    token = uuid.uuid4().hex
    SESSIONS[token] = row["user_id"]
    raise Redirect(ROLE_HOME[row["role"]] + f"::SETCOOKIE::{token}")


@route("GET", r"/logout")
def logout(environ, m, conn, user):
    cookies = parse_cookies(environ)
    SESSIONS.pop(cookies.get("sid"), None)
    raise Redirect("/login::CLEARCOOKIE::")


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


@route("GET", r"/customer/new")
def customer_new_form(environ, m, conn, user):
    require_login(user, "customer")
    devices = conn.execute("SELECT * FROM Devices WHERE customer_id=?", (user["customer_id"],)).fetchall()
    centers = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
    centers_with_geo = [c for c in centers if c["latitude"] is not None and c["longitude"] is not None]
    return render("customer_new_ticket.html", devices=devices, user=user, error=None,
                   centers=centers, centers_with_geo=centers_with_geo,
                   max_images=MAX_IMAGES, max_video_mb=MAX_VIDEO_MB)


@route("POST", r"/customer/new")
def customer_new_submit(environ, m, conn, user):
    require_login(user, "customer")
    fields, files = parse_multipart(environ)
    device_sn = fields.get("device_sn", "")

    def with_error(msg):
        devices = conn.execute("SELECT * FROM Devices WHERE customer_id=?", (user["customer_id"],)).fetchall()
        centers = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
        centers_with_geo = [c for c in centers if c["latitude"] is not None and c["longitude"] is not None]
        return render("customer_new_ticket.html", devices=devices, user=user, error=msg,
                       centers=centers, centers_with_geo=centers_with_geo,
                       max_images=MAX_IMAGES, max_video_mb=MAX_VIDEO_MB)

    owned = conn.execute(
        "SELECT 1 FROM Devices WHERE device_sn=? AND customer_id=?", (device_sn, user["customer_id"])
    ).fetchone()
    if not owned:
        return with_error("ไม่พบเครื่องพิมพ์นี้ในบัญชีของคุณ")

    any_centers = conn.execute("SELECT COUNT(*) c FROM Service_Centers").fetchone()["c"]
    center_id = fields.get("center_id") or None
    if any_centers and not center_id:
        return with_error("กรุณาเลือกสาขาที่ต้องการเข้ารับบริการ")
    if center_id:
        center_ok = conn.execute("SELECT 1 FROM Service_Centers WHERE center_id=?", (center_id,)).fetchone()
        if not center_ok:
            return with_error("สาขาที่เลือกไม่ถูกต้อง")

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
        """INSERT INTO Tickets (device_sn, issue_category, description, center_id, status, created_at)
           VALUES (?,?,?,?, 'New', ?)""",
        (device_sn, fields.get("issue_category", ""), fields.get("description", ""), center_id, db.now()),
    )
    ticket_id = cur.lastrowid

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
        """SELECT t.*, d.model, d.customer_id, sc.name AS center_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["customer_id"] != user["customer_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้")
    logs = conn.execute(
        "SELECT * FROM Service_Logs WHERE ticket_id=? ORDER BY created_at", (ticket_id,)
    ).fetchall()
    media = conn.execute("SELECT * FROM Ticket_Media WHERE ticket_id=? ORDER BY media_id", (ticket_id,)).fetchall()
    quotes = get_quotes_for_ticket(conn, ticket_id)
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    return render("customer_ticket_detail.html", t=t, logs=logs, media=media, user=user,
                   quotes=quotes, invoice_items=invoice_items, invoice_total=invoice_total,
                   status_index={s: i for i, s in enumerate(db.STATUSES)})


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

@route("GET", r"/admin/dashboard")
def admin_dashboard(environ, m, conn, user):
    require_login(user, "admin", "manager")
    counts = conn.execute(
        "SELECT status, COUNT(*) c FROM Tickets GROUP BY status"
    ).fetchall()
    counts = {r["status"]: r["c"] for r in counts}
    workload = conn.execute(
        """SELECT u.name, COUNT(t.ticket_id) open_tickets FROM Users u
           LEFT JOIN Tickets t ON t.assigned_tech_id = u.user_id AND t.status != 'Resolved/Closed'
           WHERE u.role='technician' GROUP BY u.user_id"""
    ).fetchall()
    low_stock = conn.execute(
        "SELECT * FROM Spare_Parts WHERE stock_quantity <= reorder_level"
    ).fetchall()
    centers = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
    centers_with_geo = [c for c in centers if c["latitude"] is not None and c["longitude"] is not None]
    return render("admin_dashboard.html", counts=counts, workload=workload,
                   low_stock=low_stock, user=user, total=sum(counts.values()),
                   centers=centers, centers_with_geo=centers_with_geo)


@route("GET", r"/admin/board")
def admin_board(environ, m, conn, user):
    require_login(user, "admin", "manager")
    tickets = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, u.name AS tech_name, sc.name AS center_name
           FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           LEFT JOIN Users u ON u.user_id = t.assigned_tech_id
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           ORDER BY t.created_at"""
    ).fetchall()
    board = {s: [] for s in db.STATUSES}
    for t in tickets:
        board[t["status"]].append(t)
    techs = conn.execute("SELECT * FROM Users WHERE role='technician'").fetchall()
    return render("admin_board.html", board=board, techs=techs, user=user)


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
    media = conn.execute("SELECT * FROM Ticket_Media WHERE ticket_id=? ORDER BY media_id", (ticket_id,)).fetchall()
    logs = conn.execute("SELECT * FROM Service_Logs WHERE ticket_id=? ORDER BY created_at", (ticket_id,)).fetchall()
    techs = conn.execute("SELECT * FROM Users WHERE role='technician' AND is_active=1").fetchall()
    quotes = get_quotes_for_ticket(conn, ticket_id)
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    return render("admin_ticket_detail.html", t=t, media=media, logs=logs, techs=techs, user=user,
                   quotes=quotes, invoice_items=invoice_items, invoice_total=invoice_total)


@route("POST", r"/admin/ticket/(\d+)/update")
def admin_ticket_update(environ, m, conn, user):
    require_login(user, "admin", "manager")
    ticket_id = int(m.group(1))
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
    conn.commit()
    raise Redirect(form.get("next") or "/admin/board")


@route("GET", r"/admin/customers")
def admin_customers(environ, m, conn, user):
    require_login(user, "admin", "manager")
    customers = conn.execute("SELECT * FROM Customers ORDER BY customer_id").fetchall()
    devices = conn.execute("SELECT * FROM Devices ORDER BY customer_id").fetchall()
    return render("admin_customers.html", customers=customers, devices=devices, user=user,
                   days_left=days_left)


@route("POST", r"/admin/customers/new")
def admin_customer_new(environ, m, conn, user):
    require_login(user, "admin", "manager")
    form = parse_post(environ)
    conn.execute(
        "INSERT INTO Customers (name, phone, email, line_id, address) VALUES (?,?,?,?,?)",
        (form.get("name", ""), form.get("phone", ""), form.get("email", ""),
         form.get("line_id", ""), form.get("address", "")),
    )
    conn.commit()
    raise Redirect("/admin/customers")


@route("POST", r"/admin/devices/new")
def admin_device_new(environ, m, conn, user):
    require_login(user, "admin", "manager")
    form = parse_post(environ)
    conn.execute(
        """INSERT INTO Devices (device_sn, customer_id, model, type, purchase_date, warranty_end_date)
           VALUES (?,?,?,?,?,?)""",
        (form.get("device_sn", ""), form.get("customer_id", ""), form.get("model", ""),
         form.get("type", "FDM"), form.get("purchase_date", ""), form.get("warranty_end_date", "")),
    )
    conn.commit()
    raise Redirect("/admin/customers")


@route("GET", r"/admin/inventory")
def admin_inventory(environ, m, conn, user):
    require_login(user, "admin", "manager")
    parts = conn.execute("SELECT * FROM Spare_Parts ORDER BY part_sku").fetchall()
    return render("admin_inventory.html", parts=parts, user=user, error=None,
                   threshold=db.HIGH_COST_APPROVAL_THRESHOLD, max_image_mb=MAX_PART_IMAGE_MB)


@route("POST", r"/admin/inventory/(.+)/restock")
def admin_inventory_restock(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku = m.group(1)
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
        parts = conn.execute("SELECT * FROM Spare_Parts ORDER BY part_sku").fetchall()
        return render("admin_inventory.html", parts=parts, user=user, error=msg,
                       threshold=db.HIGH_COST_APPROVAL_THRESHOLD, max_image_mb=MAX_PART_IMAGE_MB)

    if not sku or not name:
        return with_error("กรุณากรอกรหัสอะไหล่ (SKU) และชื่ออะไหล่")
    try:
        stock = int(fields.get("stock_quantity") or 0)
        cost = float(fields.get("cost_price") or 0)
        labor = float(fields.get("labor_fee") or 0)
        reorder = int(fields.get("reorder_level") or 0)
    except ValueError:
        return with_error("จำนวน/ราคา ต้องเป็นตัวเลข")

    image_file = (files.get("image") or [None])[0]
    try:
        image_filename = save_part_image(sku, image_file)
    except ValueError as e:
        return with_error(str(e))

    try:
        conn.execute(
            """INSERT INTO Spare_Parts (part_sku, part_name, compatible_models, stock_quantity,
                                         cost_price, labor_fee, reorder_level, image_filename)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sku, name, fields.get("compatible_models", ""), stock, cost, labor, reorder, image_filename),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return with_error(f"รหัสอะไหล่ (SKU) '{sku}' มีอยู่แล้วในระบบ")
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/image")
def admin_inventory_image(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku = m.group(1)
    part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
    if not part:
        raise HttpError(404, "ไม่พบอะไหล่นี้")

    fields, files = parse_multipart(environ)
    image_file = (files.get("image") or [None])[0]
    try:
        image_filename = save_part_image(sku, image_file)
    except ValueError as e:
        parts = conn.execute("SELECT * FROM Spare_Parts ORDER BY part_sku").fetchall()
        return render("admin_inventory.html", parts=parts, user=user, error=str(e),
                       threshold=db.HIGH_COST_APPROVAL_THRESHOLD, max_image_mb=MAX_PART_IMAGE_MB)

    if image_filename:
        conn.execute("UPDATE Spare_Parts SET image_filename=? WHERE part_sku=?", (image_filename, sku))
        conn.commit()
    raise Redirect("/admin/inventory")


@route("POST", r"/admin/inventory/(.+)/delete")
def admin_inventory_delete(environ, m, conn, user):
    require_login(user, "admin", "manager")
    sku = m.group(1)
    try:
        conn.execute("DELETE FROM Spare_Parts WHERE part_sku=?", (sku,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        parts = conn.execute("SELECT * FROM Spare_Parts ORDER BY part_sku").fetchall()
        return render("admin_inventory.html", parts=parts, user=user,
                       error=f"ลบ '{sku}' ไม่ได้ เนื่องจากมีประวัติการเบิกใช้อะไหล่นี้อยู่ในระบบซ่อม",
                       threshold=db.HIGH_COST_APPROVAL_THRESHOLD, max_image_mb=MAX_PART_IMAGE_MB)
    raise Redirect("/admin/inventory")


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

    if not username or not password or not name or role not in ("customer", "admin", "technician", "manager"):
        return with_error("กรุณากรอกข้อมูลให้ครบถ้วน")
    if role == "customer" and not customer_id:
        return with_error("บัญชีลูกค้าต้องเลือกผูกกับข้อมูลลูกค้าที่มีอยู่")
    if role != "customer":
        customer_id = None
    if role == "customer":
        center_id = None  # ศูนย์บริการมีไว้สำหรับ staff เท่านั้น

    try:
        conn.execute(
            "INSERT INTO Users (username, password, role, name, customer_id, center_id, is_active) VALUES (?,?,?,?,?,?,1)",
            (username, db.hash_password(password), role, name, customer_id, center_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return with_error(f"ชื่อผู้ใช้ '{username}' ถูกใช้ไปแล้ว")
    raise Redirect("/admin/users")


@route("POST", r"/admin/users/(\d+)/edit")
def admin_users_edit(environ, m, conn, user):
    require_login(user, "admin")
    target_id = int(m.group(1))
    form = parse_post(environ)
    name = form.get("name", "").strip()
    role = form.get("role", "")
    new_password = form.get("password", "").strip()
    center_id = form.get("center_id") or None
    if role == "customer":
        center_id = None

    if role not in ("customer", "admin", "technician", "manager") or not name:
        raise Redirect("/admin/users")

    if new_password:
        conn.execute(
            "UPDATE Users SET name=?, role=?, password=?, center_id=? WHERE user_id=?",
            (name, role, db.hash_password(new_password), center_id, target_id),
        )
    else:
        conn.execute("UPDATE Users SET name=?, role=?, center_id=? WHERE user_id=?",
                      (name, role, center_id, target_id))
    conn.commit()
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
    except sqlite3.IntegrityError:
        conn.rollback()
        # มีข้อมูลผูกอยู่ (เช่น ช่างที่เคยรับงานซ่อม) -> ระงับการใช้งานแทนการลบ
        conn.execute("UPDATE Users SET is_active=0 WHERE user_id=?", (target_id,))
        conn.commit()
    raise Redirect("/admin/users")


@route("GET", r"/admin/centers")
def admin_centers(environ, m, conn, user):
    require_login(user, "admin")
    centers = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
    return render("admin_centers.html", centers=centers, user=user, error=None)


@route("POST", r"/admin/centers/new")
def admin_centers_new(environ, m, conn, user):
    require_login(user, "admin")
    form = parse_post(environ)
    name = form.get("name", "").strip()

    def with_error(msg):
        centers = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
        return render("admin_centers.html", centers=centers, user=user, error=msg)

    if not name:
        return with_error("กรุณากรอกชื่อศูนย์บริการ")

    lat_raw, lng_raw = form.get("latitude", "").strip(), form.get("longitude", "").strip()
    try:
        lat = float(lat_raw) if lat_raw else None
        lng = float(lng_raw) if lng_raw else None
    except ValueError:
        return with_error("พิกัด (ละติจูด/ลองจิจูด) ต้องเป็นตัวเลข")

    conn.execute(
        "INSERT INTO Service_Centers (name, address, phone, latitude, longitude) VALUES (?,?,?,?,?)",
        (name, form.get("address", ""), form.get("phone", ""), lat, lng),
    )
    conn.commit()
    raise Redirect("/admin/centers")


@route("POST", r"/admin/centers/(\d+)/delete")
def admin_centers_delete(environ, m, conn, user):
    require_login(user, "admin")
    center_id = int(m.group(1))
    try:
        conn.execute("DELETE FROM Service_Centers WHERE center_id=?", (center_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        centers = conn.execute("SELECT * FROM Service_Centers ORDER BY center_id").fetchall()
        return render("admin_centers.html", centers=centers, user=user,
                       error="ลบไม่ได้ เนื่องจากมีผู้ใช้งานสังกัดศูนย์นี้อยู่ กรุณาย้ายผู้ใช้งานออกก่อน")
    raise Redirect("/admin/centers")


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


@route("GET", r"/tech/ticket/(\d+)")
def tech_ticket_detail(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name, sc.name AS center_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           LEFT JOIN Service_Centers sc ON sc.center_id = t.center_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["assigned_tech_id"] != user["user_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")
    parts = conn.execute("SELECT * FROM Spare_Parts ORDER BY part_name").fetchall()
    logs = conn.execute("SELECT * FROM Service_Logs WHERE ticket_id=? ORDER BY created_at", (ticket_id,)).fetchall()
    media = conn.execute("SELECT * FROM Ticket_Media WHERE ticket_id=? ORDER BY media_id", (ticket_id,)).fetchall()
    quotes = get_quotes_for_ticket(conn, ticket_id)
    invoice_items, invoice_total = build_invoice(conn, ticket_id)
    return render("tech_ticket_detail.html", t=t, parts=parts, logs=logs, media=media, user=user,
                   quotes=quotes, invoice_items=invoice_items, invoice_total=invoice_total)


@route("POST", r"/tech/ticket/(\d+)/status")
def tech_ticket_status(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    form = parse_post(environ)
    status = form.get("status")
    closed_at = db.now() if status == "Resolved/Closed" else None
    conn.execute("UPDATE Tickets SET status=?, closed_at=? WHERE ticket_id=? AND assigned_tech_id=?",
                 (status, closed_at, ticket_id, user["user_id"]))
    conn.commit()
    raise Redirect(f"/tech/ticket/{ticket_id}")


@route("POST", r"/tech/ticket/(\d+)/log")
def tech_ticket_log(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    form = parse_post(environ)
    sku = form.get("part_sku_used") or None
    qty = int(form.get("quantity_used", 0) or 0)
    try:
        labor_fee = float(form.get("labor_fee") or 0)
    except ValueError:
        labor_fee = 0
    approval_status = "auto"

    if sku and qty > 0:
        part = conn.execute("SELECT * FROM Spare_Parts WHERE part_sku=?", (sku,)).fetchone()
        cost = (part["cost_price"] if part else 0) * qty
        if cost > db.HIGH_COST_APPROVAL_THRESHOLD:
            approval_status = "pending"  # รอผู้จัดการอนุมัติก่อนตัดสต็อก

    conn.execute(
        """INSERT INTO Service_Logs (ticket_id, part_sku_used, quantity_used, action_taken, tech_notes,
                                      labor_fee, approval_status, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ticket_id, sku, qty, form.get("action_taken", ""), form.get("tech_notes", ""),
         labor_fee, approval_status, db.now()),
    )

    if sku and qty > 0 and approval_status == "auto":
        conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - ? WHERE part_sku=?", (qty, sku))

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
        part_cost = (l["cost_price"] or 0) * (l["quantity_used"] or 0) if l["part_sku_used"] else 0
        labor = l["labor_fee"] or 0
        desc = l["action_taken"] or "งานซ่อม"
        if l["part_name"]:
            desc += f" ({l['part_name']} x{l['quantity_used']})"
        rows.append({
            "log_id": l["log_id"], "created_at": l["created_at"], "description": desc,
            "suggested_price": round(part_cost + labor, 2),
        })
    return rows


@route("GET", r"/tech/ticket/(\d+)/quote/new")
def tech_quote_form(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t or t["assigned_tech_id"] != user["user_id"]:
        raise HttpError(404, "ไม่พบตั๋วซ่อมนี้ หรือไม่ได้รับมอบหมายให้คุณ")
    loggable = get_loggable_items(conn, ticket_id)
    return render("tech_quote_form.html", t=t, loggable=loggable, user=user, error=None)


@route("POST", r"/tech/ticket/(\d+)/quote/new")
def tech_quote_submit(environ, m, conn, user):
    require_login(user, "technician")
    ticket_id = int(m.group(1))
    t = conn.execute(
        """SELECT t.*, d.model, c.name AS customer_name FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=? AND t.assigned_tech_id=?""",
        (ticket_id, user["user_id"]),
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
        items.append({"description": row["description"], "quantity": 1, "unit_price": price})

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
            "INSERT INTO Quotation_Items (quote_id, description, quantity, unit_price) VALUES (?,?,?,?)",
            (quote_id, it["description"], it["quantity"], it["unit_price"]),
        )
    conn.commit()
    raise Redirect(f"/tech/ticket/{ticket_id}")


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
           WHERE sl.approval_status='pending' ORDER BY sl.created_at"""
    ).fetchall()
    return render("manager_approvals.html", pending=pending, user=user)


@route("POST", r"/manager/approvals/(\d+)/(approve|reject)")
def manager_approve(environ, m, conn, user):
    require_login(user, "manager")
    log_id, action = int(m.group(1)), m.group(2)
    log = conn.execute("SELECT * FROM Service_Logs WHERE log_id=?", (log_id,)).fetchone()
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
           WHERE t.csat_score IS NOT NULL ORDER BY t.closed_at DESC"""
    ).fetchall()
    scores = [r["csat_score"] for r in rows if r["csat_score"] is not None]
    avg = round(sum(scores) / len(scores), 2) if scores else None
    return render("manager_csat.html", rows=rows, avg=avg, user=user)


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
        """SELECT t.*, d.model, c.name AS customer_name, c.phone, c.address FROM Tickets t
           JOIN Devices d ON d.device_sn = t.device_sn
           JOIN Customers c ON c.customer_id = d.customer_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    items = conn.execute(
        "SELECT * FROM Quotation_Items WHERE quote_id=? ORDER BY item_id", (quote_id,)
    ).fetchall()
    total = sum((it["quantity"] or 0) * (it["unit_price"] or 0) for it in items)
    creator = conn.execute("SELECT name FROM Users WHERE user_id=?", (q["created_by"],)).fetchone()
    return render("quote_print.html", q=q, t=t, items=items, total=round(total, 2),
                   creator_name=creator["name"] if creator else "-")


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


# ------------------------------------------------------------- WSGI app --

def serve_static(path, start_response):
    fs_path = os.path.join(STATIC_DIR, path.replace("/static/", "", 1))
    if not os.path.abspath(fs_path).startswith(os.path.abspath(STATIC_DIR)) or not os.path.isfile(fs_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]
    ctype, _ = mimetypes.guess_type(fs_path)
    with open(fs_path, "rb") as f:
        data = f.read()
    start_response("200 OK", [("Content-Type", ctype or "application/octet-stream")])
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


def serve_part_image(path, user, start_response):
    """เสิร์ฟรูปอะไหล่ — เฉพาะผู้ใช้ที่ล็อกอินแล้วเท่านั้น (ข้อมูลคลังอะไหล่เป็นข้อมูลภายในร้าน)"""
    if not user:
        start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8")])
        return ["<h1>403</h1><p>ไม่มีสิทธิ์เข้าถึงไฟล์นี้</p>".encode("utf-8")]

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


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    if path.startswith("/static/"):
        return serve_static(path, start_response)

    conn = db.get_conn()
    try:
        user = get_current_user(environ, conn)

        if path.startswith("/media/") and method == "GET":
            return serve_media(path, conn, user, start_response)

        if path.startswith("/part-image/") and method == "GET":
            return serve_part_image(path, user, start_response)

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
                        loc, token = loc.split("::SETCOOKIE::")
                        set_cookie = f"sid={token}; Path=/; HttpOnly"
                    elif "::CLEARCOOKIE::" in loc:
                        loc = loc.replace("::CLEARCOOKIE::", "")
                        set_cookie = "sid=; Path=/; Max-Age=0"
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


if __name__ == "__main__":
    db.init_db()
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(PART_IMAGES_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 8000))
    print(f"Repair Ticketing System running on http://localhost:{port}")
    with make_server("0.0.0.0", port, application) as httpd:
        httpd.serve_forever()
