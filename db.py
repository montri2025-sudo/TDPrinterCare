# -*- coding: utf-8 -*-
"""Database access layer: connection, schema init, and demo seed data."""
import sqlite3
import hashlib
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "repair.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

STATUSES = [
    "New",
    "Diagnosing",
    "Waiting for Parts",
    "In Repair",
    "Testing",
    "Resolved/Closed",
]

# ราคาอะไหล่ที่สูงกว่านี้ ต้องรอผู้จัดการอนุมัติก่อนตัดสต็อก
HIGH_COST_APPROVAL_THRESHOLD = 2000


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db(reset: bool = False):
    """Create tables (if not present) and seed demo data on first run."""
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_conn()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())

    cur = conn.execute("SELECT COUNT(*) AS c FROM Users")
    if cur.fetchone()["c"] == 0:
        _seed(conn)

    conn.commit()
    conn.close()


def _seed(conn: sqlite3.Connection):
    # --- ลูกค้า ---
    conn.execute(
        "INSERT INTO Customers (customer_id, name, phone, email, line_id, address) "
        "VALUES (1, 'คุณสมศรี ใจดี', '081-234-5678', 'somsri@example.com', 'somsri_line', '123 ถ.สุขุมวิท กรุงเทพฯ')"
    )
    conn.execute(
        "INSERT INTO Customers (customer_id, name, phone, email, line_id, address) "
        "VALUES (2, 'คุณอนันต์ พิมพ์ดี', '089-999-1234', 'anan@example.com', 'anan_line', '45 ถ.รัชดาภิเษก กรุงเทพฯ')"
    )

    # --- เครื่องพิมพ์ ---
    conn.execute(
        "INSERT INTO Devices (device_sn, customer_id, model, type, purchase_date, warranty_end_date) "
        "VALUES ('AC-KOBRA2-0001', 1, 'Kobra 2', 'FDM', '2025-01-10', '2026-12-31')"
    )
    conn.execute(
        "INSERT INTO Devices (device_sn, customer_id, model, type, purchase_date, warranty_end_date) "
        "VALUES ('AC-M5S-0002', 2, 'Photon M5s', 'Resin', '2024-03-05', '2025-03-05')"
    )

    # --- ศูนย์บริการ ---
    conn.execute(
        "INSERT INTO Service_Centers (center_id, name, address, phone, latitude, longitude) "
        "VALUES (1, 'TDPrinter Care สาขาสุขุมวิท', '123 ถ.สุขุมวิท กรุงเทพฯ', '02-111-2222', 13.7440, 100.5622)"
    )
    conn.execute(
        "INSERT INTO Service_Centers (center_id, name, address, phone, latitude, longitude) "
        "VALUES (2, 'TDPrinter Care สาขารัชดา', '45 ถ.รัชดาภิเษก กรุงเทพฯ', '02-333-4444', 13.7734, 100.5697)"
    )

    # --- ผู้ใช้งาน (4 สิทธิ์) — center_id: ศูนย์บริการที่สังกัด (เฉพาะ staff) ---
    users = [
        ("admin1", "admin123", "admin", "แอดมิน สมชาย", None, 1),
        ("tech1", "tech123", "technician", "ช่างเอก", None, 1),
        ("tech2", "tech123", "technician", "ช่างบี", None, 2),
        ("mgr1", "mgr123", "manager", "ผจก. สมหญิง", None, 1),
        ("cust1", "cust123", "customer", "คุณสมศรี ใจดี", 1, None),
        ("cust2", "cust123", "customer", "คุณอนันต์ พิมพ์ดี", 2, None),
    ]
    for username, pwd, role, name, customer_id, center_id in users:
        conn.execute(
            "INSERT INTO Users (username, password, role, name, customer_id, center_id) VALUES (?,?,?,?,?,?)",
            (username, hash_password(pwd), role, name, customer_id, center_id),
        )

    # --- คลังอะไหล่ (สุดท้าย: ค่าบริการเปลี่ยนอุปกรณ์มาตรฐานต่อชิ้น) ---
    parts = [
        ("NZ-04", "หัวฉีด 0.4mm", "Kobra 2, Kobra 3", 20, 150, 100, 5),
        ("LCD-MONO", "จอ LCD Mono", "Photon M5s, Photon Mono", 2, 2500, 300, 3),
        ("FEP-01", "แผ่น FEP", "Photon Series", 15, 300, 50, 5),
        ("MB-KOBRA2", "เมนบอร์ด Kobra 2", "Kobra 2", 1, 3200, 500, 2),
        ("BELT-01", "สายพาน GT2", "Kobra 2, Kobra 3", 10, 120, 100, 4),
    ]
    for sku, pname, models, qty, cost, labor, reorder in parts:
        conn.execute(
            "INSERT INTO Spare_Parts (part_sku, part_name, compatible_models, stock_quantity, cost_price, labor_fee, reorder_level) "
            "VALUES (?,?,?,?,?,?,?)",
            (sku, pname, models, qty, cost, labor, reorder),
        )

    # --- ตัวอย่างตั๋วซ่อม ---
    tech1_id = conn.execute("SELECT user_id FROM Users WHERE username='tech1'").fetchone()["user_id"]
    conn.execute(
        "INSERT INTO Tickets (device_sn, issue_category, description, status, assigned_tech_id, center_id, created_at) "
        "VALUES ('AC-KOBRA2-0001', 'พิมพ์ไม่ติด', 'พิมพ์แล้วชิ้นงานไม่เกาะแผ่น หลุดตั้งแต่เลเยอร์แรก', 'In Repair', ?, 1, ?)",
        (tech1_id, now()),
    )
    conn.execute(
        "INSERT INTO Tickets (device_sn, issue_category, description, status, center_id, created_at) "
        "VALUES ('AC-M5S-0002', 'เปิดไม่ติด', 'กดปุ่มเปิดเครื่องแล้วไม่มีไฟขึ้นเลย', 'New', 2, ?)",
        (now(),),
    )
