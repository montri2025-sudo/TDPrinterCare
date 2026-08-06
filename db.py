# -*- coding: utf-8 -*-
"""Database access layer: connection, schema init, and demo seed data.

ใช้ MySQL (ผ่าน PyMySQL) เป็นฐานข้อมูลหลัก ตั้งค่าการเชื่อมต่อผ่าน environment
variables (ค่าเริ่มต้นตรงกับ docker-compose.yml ที่แนบมาให้):

    MYSQL_HOST      ค่าเริ่มต้น 127.0.0.1
    MYSQL_PORT      ค่าเริ่มต้น 3306
    MYSQL_USER      ค่าเริ่มต้น tdprinter
    MYSQL_PASSWORD  ค่าเริ่มต้น tdprinter_pw
    MYSQL_DATABASE  ค่าเริ่มต้น tdprinter_care

ชั้นนี้ครอบ PyMySQL ไว้ด้วย wrapper บางๆ (_Conn) เพื่อให้ส่วนที่เหลือของแอป
(app.py) ยังเรียกแบบเดิมสไตล์ sqlite3 ได้ต่อไป — `conn.execute(sql, params)`
พร้อม placeholder แบบ `?` — โดยแปลงเป็น `%s` และ cursor เป็น DictCursor ให้
อัตโนมัติ (แถวที่ได้เป็น dict เข้าถึงด้วย row["col"] ได้เหมือน sqlite3.Row เดิม)
"""
import hashlib
import hmac
import os
import datetime

import pymysql
import pymysql.cursors
from pymysql.err import IntegrityError  # re-export ให้ app.py import จาก db แทน

MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "tdprinter")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "tdprinter_pw")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "tdprinter_care")

# ตั้งเป็น "0" เพื่อปิดการใส่ข้อมูลตัวอย่าง/บัญชีทดสอบ (admin1/admin123 ฯลฯ) ตอน deploy จริง —
# ค่าเริ่มต้นเป็น "1" เพื่อความสะดวกตอน dev/demo เท่านั้น
SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "1") != "0"

# ใช้สร้างบัญชีแอดมินคนแรกอัตโนมัติเมื่อปิด SEED_DEMO_DATA ไว้ (ฐานข้อมูลว่างแต่ไม่อยากได้บัญชีทดสอบ) —
# ถ้าไม่ตั้งค่าไว้ จะไม่มีบัญชีใดๆ เลยและต้อง insert บัญชีแรกเข้า Users เองผ่าน SQL
INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME")
INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD")

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

STATUSES = [
    "New",
    "Diagnosing",
    "Waiting for Parts",
    "In Repair",
    "Testing",
    "Resolved/Closed",
]

# ป้ายชื่อสถานะภาษาไทยที่แสดงผลให้ผู้ใช้เห็น — ค่าที่เก็บจริงในฐานข้อมูล/ใช้เทียบเงื่อนไขใน SQL
# ยังคงเป็นภาษาอังกฤษเหมือนเดิมทุกที่ (STATUSES ด้านบน) เปลี่ยนแค่ข้อความที่แสดงบนหน้าเว็บเท่านั้น
STATUS_LABELS = {
    "New": "รอซ่อม",
    "Diagnosing": "กำลังตรวจสอบ",
    "Waiting for Parts": "รออะไหล่",
    "In Repair": "กำลังซ่อม",
    "Testing": "ทดสอบ",
    "Resolved/Closed": "เรียบร้อยแล้ว",
}

# สัญลักษณ์ (emoji) ประจำสถานะตั๋วซ่อม — ใช้แสดงคู่กับ STATUS_LABELS ในหน้ารายงาน/สรุปผลต่างๆ ให้ดูเข้าใจง่ายขึ้น
STATUS_ICONS = {
    "New": "🆕",
    "Diagnosing": "🔍",
    "Waiting for Parts": "⏳",
    "In Repair": "🔧",
    "Testing": "🧪",
    "Resolved/Closed": "✅",
}

# ราคาอะไหล่ที่สูงกว่านี้ ต้องรอผู้จัดการอนุมัติก่อนตัดสต็อก
HIGH_COST_APPROVAL_THRESHOLD = 2000

# รอบการแจ้งเตือนบำรุงรักษาเครื่องพิมพ์ (นับจากวันที่บำรุงรักษาครั้งล่าสุด) — ค่าเริ่มต้น 30 วัน (รายเดือน)
# (ใช้เป็นค่า default เดิมสำหรับ backward-compat เท่านั้น — ตั้งแต่มีระบบ Maintenance Plan/Scheduler
# ด้านล่าง รอบบำรุงรักษาจริงจะคำนวณจาก Maintenance_Plan_Items แทน ไม่ใช้ค่านี้แล้ว)
MAINTENANCE_INTERVAL_DAYS = 30

DEVICE_TYPES = ["FDM", "Resin", "Wash & Cure", "Other"]

MAINTENANCE_INTERVAL_TYPE_LABELS = {"days": "วัน", "hours": "ชั่วโมง"}

# --- Alert & Notification: ตั้งค่าอีเมล (SMTP) ผ่าน environment variables ---------------
# ถ้าไม่ตั้ง SMTP_HOST ไว้ ระบบจะยังสร้างการแจ้งเตือนในแอป (in-app) ให้ตามปกติ แต่จะไม่พยายามส่งอีเมล
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or SMTP_USER
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1") != "0"

# --- สมัครสมาชิก/ล็อกอินด้วย Google หรือ LINE (OAuth2) ผ่าน environment variables -------------
# ต้องไปสร้างแอป OAuth เองที่ Google Cloud Console (https://console.cloud.google.com/apis/credentials)
# และ/หรือ LINE Developers Console (https://developers.line.biz/console/) แล้วนำ Client ID/Secret
# มาใส่ไว้ที่นี่ — ถ้าไม่ตั้งค่าไว้ ปุ่มที่เกี่ยวข้องในหน้าสมัครสมาชิกจะแสดงเป็นสถานะ "ยังไม่พร้อมใช้งาน"
# PUBLIC_BASE_URL ต้องตรงกับโดเมนจริงที่ใช้งาน (เช่น https://servicepro.tdprinter.com) เพื่อประกอบ
# redirect URI ให้ตรงกับที่ลงทะเบียนไว้ในคอนโซลของ Google/LINE ทุกตัวอักษร (รวม http/https)
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
LINE_CHANNEL_ID = os.environ.get("LINE_CHANNEL_ID", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

DEFAULT_DEVICE_QUOTA = 3  # จำนวนเครื่องพิมพ์เริ่มต้นที่ลูกค้าใหม่ลงทะเบียนเองได้ — แอดมินปรับเพิ่มได้ต่อลูกค้าที่หน้าลูกค้า/เครื่อง


PBKDF2_ITERATIONS = 260_000


def hash_password(raw: str) -> str:
    """เข้ารหัสผ่านด้วย PBKDF2-HMAC-SHA256 + salt สุ่มต่อผู้ใช้แต่ละคน (เก็บ salt/รอบ/ผลลัพธ์
    รวมในสตริงเดียว คั่นด้วย $) ปลอดภัยกว่า SHA-256 เปล่าๆ มาก เพราะทนต่อ rainbow table และ
    การ brute-force แบบ GPU ได้ดีกว่า (ไม่ต้องพึ่งไลบรารีภายนอกอย่าง bcrypt/argon2)"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITERATIONS, salt.hex(), dk.hex())


def verify_password(raw: str, stored: str) -> bool:
    """ตรวจสอบรหัสผ่านกับค่าที่เก็บไว้ — รองรับทั้งรูปแบบใหม่ (pbkdf2_sha256$...) และรูปแบบเก่า
    (SHA-256 ธรรมดาไม่มี salt จากเวอร์ชันก่อนหน้า) เพื่อไม่ให้บัญชีที่เคย deploy ไปแล้ว login ไม่ได้
    ใช้ hmac.compare_digest กันการโจมตีแบบ timing attack"""
    if not stored or not raw:
        return False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _scheme, iterations_s, salt_hex, hash_hex = stored.split("$")
            iterations = int(iterations_s)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
        except (ValueError, AttributeError):
            return False
        dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)
    # รูปแบบเก่า: SHA-256 hex digest ไม่มี salt (จากเวอร์ชันก่อนหน้าของระบบนี้)
    legacy_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_digest, stored)


class _Conn:
    """แปลง PyMySQL connection ให้ใช้งานสไตล์ sqlite3.Connection.execute(...)"""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executescript(self, script: str):
        cur = self._raw.cursor()
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        return cur

    def cursor(self):
        return self._raw.cursor()

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def _connect_raw(use_database=True):
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE if use_database else None,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def get_conn() -> _Conn:
    return _Conn(_connect_raw())


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_database():
    """สร้างฐานข้อมูล (CREATE DATABASE) ถ้ายังไม่มี เผื่อกรณีที่ยังไม่ได้เตรียมไว้ล่วงหน้า"""
    raw = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, charset="utf8mb4",
    )
    try:
        with raw.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `%s` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" % MYSQL_DATABASE
            )
        raw.commit()
    finally:
        raw.close()


def init_db(reset: bool = False):
    """Create tables (if not present) and seed demo data on first run."""
    _ensure_database()
    conn = get_conn()

    if reset:
        # ลบตารางทั้งหมดแล้วสร้างใหม่ (ใช้เวลา dev/testing เท่านั้น — ข้อมูลหายหมด)
        cur = conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        cur.execute("SHOW TABLES")
        tables = [list(row.values())[0] for row in cur.fetchall()]
        for table in tables:
            cur.execute("DROP TABLE IF EXISTS `%s`" % table)
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()

    _migrate_schema(conn)

    cur = conn.execute("SELECT COUNT(*) AS c FROM Users")
    if cur.fetchone()["c"] == 0:
        if SEED_DEMO_DATA:
            print("=" * 78)
            print("[init_db] ฐานข้อมูลว่าง -> กำลังใส่ข้อมูลตัวอย่าง/บัญชีทดสอบ (SEED_DEMO_DATA=1)")
            print("[init_db] คำเตือน: บัญชีทดสอบเหล่านี้ (admin1/admin123 ฯลฯ) มีรหัสผ่านที่รู้กันทั่วไป")
            print("[init_db] ก่อนใช้งานจริง ต้องเปลี่ยนรหัสผ่านทุกบัญชี หรือปิดการ seed ด้วย SEED_DEMO_DATA=0")
            print("=" * 78)
            _seed(conn)
            conn.commit()
        elif INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD:
            print(f"[init_db] SEED_DEMO_DATA=0 -> สร้างบัญชีแอดมินคนแรกจาก INITIAL_ADMIN_USERNAME "
                  f"('{INITIAL_ADMIN_USERNAME}') แทนข้อมูลตัวอย่าง")
            conn.execute(
                "INSERT INTO Users (username, password, role, name, is_active) VALUES (?,?,?,?,1)",
                (INITIAL_ADMIN_USERNAME, hash_password(INITIAL_ADMIN_PASSWORD), "admin", "ผู้ดูแลระบบ"),
            )
            conn.commit()
        else:
            print("[init_db] ฐานข้อมูลว่างและ SEED_DEMO_DATA=0 -> ข้ามการใส่ข้อมูลตัวอย่าง "
                  "กรุณาตั้งค่า INITIAL_ADMIN_USERNAME/INITIAL_ADMIN_PASSWORD "
                  "หรือสร้างบัญชีแอดมินคนแรกเองผ่าน SQL ก่อนเข้าใช้งาน")

    conn.close()


def _column_exists(conn, table, column):
    row = conn.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=? AND TABLE_NAME=? AND COLUMN_NAME=?""",
        (MYSQL_DATABASE, table, column),
    ).fetchone()
    return row is not None


def _enum_has_value(conn, table, column, value):
    """ตรวจว่าคอลัมน์ชนิด ENUM มีค่านี้อยู่ในนิยามแล้วหรือยัง — ใช้ก่อน ALTER ... MODIFY COLUMN
    เพื่อขยายรายการค่าที่ ENUM รองรับ กันรันซ้ำโดยไม่จำเป็นทุกครั้งที่แอปสตาร์ท"""
    row = conn.execute(
        """SELECT COLUMN_TYPE AS t FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=? AND TABLE_NAME=? AND COLUMN_NAME=?""",
        (MYSQL_DATABASE, table, column),
    ).fetchone()
    if not row:
        return False
    return f"'{value}'" in row["t"]


def _migrate_schema(conn: _Conn):
    """แก้ schema ของฐานข้อมูลที่มีอยู่แล้ว (deploy จริงที่มีข้อมูลค้างอยู่) ให้ตามทันไฟล์
    schema.sql เวอร์ชันล่าสุด — CREATE TABLE IF NOT EXISTS ด้านบนจะไม่เพิ่มคอลัมน์ใหม่ให้ตาราง
    ที่มีอยู่แล้ว จึงต้องมี ALTER TABLE เสริมตรงนี้ทุกครั้งที่เพิ่มคอลัมน์ใหม่ในอนาคต (idempotent
    ตรวจสอบก่อนว่ามีคอลัมน์อยู่แล้วหรือยัง กันรันซ้ำพัง)"""
    if not _column_exists(conn, "Quotation_Items", "tech_notes"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Quotation_Items.tech_notes")
        conn.execute("ALTER TABLE Quotation_Items ADD COLUMN tech_notes TEXT")
        conn.commit()

    if not _column_exists(conn, "Devices", "status"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Devices.status (ค่าเริ่มต้น 'Active' ให้เครื่องเดิมทุกเครื่อง)")
        conn.execute(
            "ALTER TABLE Devices ADD COLUMN status ENUM('Active','Decommissioned','Sold') NOT NULL DEFAULT 'Active'"
        )
        conn.commit()

    if not _column_exists(conn, "Spare_Parts", "category"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Spare_Parts.category (ค่าเริ่มต้น 'Spare_Part' ให้สินค้าเดิมทุกชิ้น)")
        conn.execute(
            """ALTER TABLE Spare_Parts ADD COLUMN category
               ENUM('FDM_Printer','Resin_Printer','Spare_Part','Material','Other')
               NOT NULL DEFAULT 'Spare_Part'"""
        )
        conn.commit()

    if not _column_exists(conn, "Devices", "created_at"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Devices.created_at (เครื่องเดิมจะเป็น NULL — ใช้เรียงเครื่องที่เพิ่มล่าสุดขึ้นก่อน)")
        conn.execute("ALTER TABLE Devices ADD COLUMN created_at TEXT")
        conn.commit()

    if not _column_exists(conn, "Customers", "tax_id"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Customers.tax_id (เลขประจำตัวผู้เสียภาษี)")
        conn.execute("ALTER TABLE Customers ADD COLUMN tax_id VARCHAR(20)")
        conn.commit()

    if not _enum_has_value(conn, "Devices", "type", "Wash & Cure"):
        print("[init_db] migrate: ขยายชนิดข้อมูล Devices.type ให้รองรับ 'Wash & Cure' และ 'Other'")
        conn.execute("ALTER TABLE Devices MODIFY COLUMN type ENUM('FDM','Resin','Wash & Cure','Other')")
        conn.commit()

    if not _column_exists(conn, "Spare_Parts", "description"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Spare_Parts.description (รายละเอียดสินค้า)")
        conn.execute("ALTER TABLE Spare_Parts ADD COLUMN description TEXT")
        conn.commit()

    if not _column_exists(conn, "Service_Logs", "is_claim"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Service_Logs.is_claim (เคลมประกัน — ค่าเริ่มต้น 0 ให้ประวัติเดิมทุกรายการ)")
        conn.execute("ALTER TABLE Service_Logs ADD COLUMN is_claim TINYINT(1) NOT NULL DEFAULT 0")
        conn.commit()
    # ตาราง Payments เป็นตารางใหม่ทั้งตาราง — CREATE TABLE IF NOT EXISTS ใน schema.sql ด้านบนจัดการให้แล้ว ไม่ต้อง ALTER

    if not _column_exists(conn, "Devices", "total_usage_hours"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Devices.total_usage_hours (ชั่วโมงใช้งานสะสม — ค่าเริ่มต้น 0 ให้เครื่องเดิมทุกเครื่อง)")
        conn.execute("ALTER TABLE Devices ADD COLUMN total_usage_hours DOUBLE NOT NULL DEFAULT 0")
        conn.commit()

    if not _column_exists(conn, "Maintenance_Logs", "plan_item_id"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Maintenance_Logs.plan_item_id/hours_at_maintenance/parts_replaced")
        conn.execute("ALTER TABLE Maintenance_Logs ADD COLUMN plan_item_id INT")
        conn.execute("ALTER TABLE Maintenance_Logs ADD COLUMN hours_at_maintenance DOUBLE")
        conn.execute("ALTER TABLE Maintenance_Logs ADD COLUMN parts_replaced TEXT")
        conn.execute(
            "ALTER TABLE Maintenance_Logs ADD CONSTRAINT fk_maint_plan_item "
            "FOREIGN KEY (plan_item_id) REFERENCES Maintenance_Plan_Items(plan_item_id)"
        )
        conn.commit()
    # ตาราง Maintenance_Plan_Items / Checklist_Items / Print_Sessions / Notifications เป็นตารางใหม่ทั้งตาราง —
    # CREATE TABLE IF NOT EXISTS ใน schema.sql ด้านบนจัดการให้แล้ว ไม่ต้อง ALTER

    if not _column_exists(conn, "Customers", "device_quota"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Customers.device_quota (โควตาเครื่องพิมพ์ลงทะเบียนเอง ค่าเริ่มต้น 3 ให้ลูกค้าเดิมทุกคน)")
        conn.execute(f"ALTER TABLE Customers ADD COLUMN device_quota INT NOT NULL DEFAULT {DEFAULT_DEVICE_QUOTA}")
        conn.commit()

    if not _column_exists(conn, "Users", "auth_provider"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Users.auth_provider/oauth_sub (รองรับสมัคร/ล็อกอินด้วย Google หรือ LINE)")
        conn.execute("ALTER TABLE Users ADD COLUMN auth_provider ENUM('local','google','line') NOT NULL DEFAULT 'local'")
        conn.execute("ALTER TABLE Users ADD COLUMN oauth_sub VARCHAR(255)")
        conn.execute("ALTER TABLE Users ADD CONSTRAINT uniq_oauth_account UNIQUE (auth_provider, oauth_sub)")
        conn.commit()

    if not _column_exists(conn, "Devices", "purchase_proof_filename"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Devices.purchase_proof_filename (หลักฐานการสั่งซื้อ)")
        conn.execute("ALTER TABLE Devices ADD COLUMN purchase_proof_filename TEXT")
        conn.commit()

    if not _column_exists(conn, "Spare_Parts", "ownership"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Spare_Parts.ownership (ค่าเริ่มต้น 'owned' ให้สินค้าเดิมทุกชิ้น — "
              "ไม่กระทบสินค้าที่เคยมีอยู่ก่อนฟีเจอร์ฝากขายพาร์ตเนอร์)")
        conn.execute(
            "ALTER TABLE Spare_Parts ADD COLUMN ownership ENUM('owned','consignment') NOT NULL DEFAULT 'owned'"
        )
        conn.commit()
    # ตาราง Restock_Orders / Restock_Order_Items / Consignment_Settlements เป็นตารางใหม่ทั้งตาราง —
    # CREATE TABLE IF NOT EXISTS ใน schema.sql ด้านบนจัดการให้แล้ว ไม่ต้อง ALTER

    if not _column_exists(conn, "Tickets", "invoice_recorded"):
        print("[init_db] migrate: เพิ่มคอลัมน์ Tickets.invoice_recorded/invoice_recorded_at/invoice_recorded_by "
              "(ติ๊กว่าลงบันทึกใบแจ้งหนี้ในบัญชีแล้วหรือยัง — ค่าเริ่มต้น 0/ยังไม่ได้บันทึก ให้ตั๋วเดิมทุกใบ)")
        conn.execute("ALTER TABLE Tickets ADD COLUMN invoice_recorded TINYINT(1) NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE Tickets ADD COLUMN invoice_recorded_at TEXT")
        conn.execute("ALTER TABLE Tickets ADD COLUMN invoice_recorded_by INT")
        conn.commit()

    # ใส่แผนบำรุงรักษา/รายการตรวจสอบก่อนพิมพ์เริ่มต้นให้อัตโนมัติถ้ายังไม่มีเลยในระบบ (ไม่ผูกกับ SEED_DEMO_DATA
    # เพราะเป็น "ค่าตั้งต้นของระบบ" ไม่ใช่ข้อมูลตัวอย่าง/บัญชีทดสอบ — แอดมินแก้ไข/เพิ่มเองภายหลังได้ที่หน้าจัดการ)
    if conn.execute("SELECT COUNT(*) c FROM Maintenance_Plan_Items").fetchone()["c"] == 0:
        print("[init_db] migrate: ใส่แผนบำรุงรักษาเริ่มต้น (Maintenance_Plan_Items)")
        _seed_default_maintenance_plans(conn)
        conn.commit()
    if conn.execute("SELECT COUNT(*) c FROM Checklist_Items").fetchone()["c"] == 0:
        print("[init_db] migrate: ใส่รายการตรวจสอบก่อนพิมพ์เริ่มต้น (Checklist_Items)")
        _seed_default_checklist_items(conn)
        conn.commit()

    # เพิ่มแผนบำรุงรักษา/checklist เรซินแบบละเอียดขึ้นตามตารางบำรุงรักษาที่ผู้ใช้ระบุ — รันทุกครั้งที่
    # ระบบเริ่มทำงาน (ไม่ผูกกับ COUNT(*)==0) เพื่อให้ระบบที่เคย seed ชุดแรกไปแล้วได้รายการชุดนี้เพิ่มด้วย
    # (ฟังก์ชันเช็ค task_name/label ซ้ำก่อน insert เองแล้ว จึงเรียกซ้ำได้ทุกครั้งอย่างปลอดภัย)
    _seed_resin_maintenance_v2(conn)
    conn.commit()


def _seed_default_maintenance_plans(conn: _Conn):
    """แผนบำรุงรักษาเริ่มต้น — ครอบคลุมทั้งรอบแบบวัน (สัปดาห์/เดือน) และแบบชั่วโมงใช้งาน (50/200/500 ชม.)
    ตามตัวอย่างที่ระบุไว้ตอนขอฟีเจอร์นี้ (ทาจาระบี/เปลี่ยนหัวฉีด) แอดมินแก้ไข/เพิ่มลบเองภายหลังได้"""
    plans = [
        (None, "ทำความสะอาดทั่วไป (ตัวเครื่อง/พัดลม/ราง)", "days", 7),
        (None, "ตรวจสอบสายไฟ/สายพาน/น็อตยึดจุดต่างๆ", "days", 30),
        ("FDM", "ทาจาระบีแกน X/Y/Z", "hours", 200),
        ("FDM", "เปลี่ยนหัวฉีด (Nozzle)", "hours", 500),
        ("FDM", "ทำความสะอาด/ปรับระดับฐานพิมพ์ (Bed Leveling)", "hours", 50),
        ("Resin", "เปลี่ยน/กรองเรซิ่นและทำความสะอาดถัง", "hours", 50),
        ("Resin", "เปลี่ยนแผ่น FEP", "hours", 200),
        ("Resin", "ทำความสะอาดแผง LCD/กระจก UV", "hours", 50),
    ]
    for device_type, task_name, interval_type, interval_value in plans:
        conn.execute(
            "INSERT INTO Maintenance_Plan_Items (device_type, task_name, interval_type, interval_value, is_active, created_at) "
            "VALUES (?,?,?,?,1,?)",
            (device_type, task_name, interval_type, interval_value, now()),
        )


def _seed_default_checklist_items(conn: _Conn):
    """รายการตรวจสอบก่อนพิมพ์เริ่มต้น (บังคับติ๊กครบก่อนเริ่มงานพิมพ์ทุกครั้ง) แยกตามประเภทเครื่อง
    บวกรายการทั่วไปที่ใช้กับทุกประเภท (device_type=NULL) แอดมินแก้ไข/เพิ่มลบเองภายหลังได้"""
    items = [
        (None, "ตรวจสอบพื้นที่รอบเครื่องปลอดภัย ไม่มีวัสดุไวไฟใกล้เครื่อง", 1),
        (None, "ตรวจสอบสายไฟ/สายเชื่อมต่อไม่มีความเสียหาย", 2),
        ("FDM", "ทำความสะอาดฐานพิมพ์ (Bed) ให้ปราศจากคราบ/เศษพลาสติก", 10),
        ("FDM", "ตรวจสอบเส้นพลาสติก (Filament) เหลือเพียงพอสำหรับงานนี้", 11),
        ("FDM", "ตรวจสอบหัวฉีดไม่อุดตัน และปรับระดับฐานพิมพ์แล้ว", 12),
        ("Resin", "ตรวจสอบปริมาณเรซิ่นในถังเพียงพอสำหรับงานนี้", 20),
        ("Resin", "ทำความสะอาดแผ่น FEP และกระจก LCD ไม่มีคราบ/รอยขีดข่วน", 21),
        ("Resin", "สวมอุปกรณ์ป้องกัน (ถุงมือ/แว่นตา) ก่อนสัมผัสเรซิ่น", 22),
    ]
    for device_type, label, sort_order in items:
        conn.execute(
            "INSERT INTO Checklist_Items (device_type, label, sort_order, is_active, created_at) VALUES (?,?,?,1,?)",
            (device_type, label, sort_order, now()),
        )


def _seed_resin_maintenance_v2(conn: _Conn):
    """แผนบำรุงรักษา/checklist เครื่องพิมพ์เรซินแบบละเอียด ตามตารางบำรุงรักษาที่ผู้ใช้ให้มา (ครอบคลุมก่อน-หลัง
    พิมพ์ทุกครั้ง, เมื่อพิมพ์เสีย, รายสัปดาห์/เดือน/3-6เดือน) — เรียกทุกครั้งที่ระบบเริ่มทำงาน (ไม่ผูกกับ
    COUNT(*)==0 เหมือนชุด seed แรกเริ่ม) เพื่อให้ระบบที่ deploy ไปแล้วก่อนหน้านี้ได้รายการชุดนี้เพิ่มด้วย —
    เช็คจาก task_name/label ที่ซ้ำกันก่อน insert ทุกครั้งกันรันซ้ำแล้วเพิ่มซ้ำ ไม่ลบ/แก้รายการเดิมที่เคย
    seed ไว้ก่อนหน้า (เผื่อมีประวัติบำรุงรักษาอ้างอิง plan_item_id เดิมอยู่แล้ว) — แอดมินลบ/ปิดใช้งานรายการ
    ที่เห็นว่าซ้ำซ้อนกับของเดิมเองได้ที่ /admin/maintenance-plans และ /admin/checklist-items"""
    new_plans = [
        ("Resin", "ตรวจสอบ/เช็ดคราบเรซินที่หน้าจอ LCD และฟิล์มกันรอย (ถ้ามีให้เช็ดด้วย IPA ทันที ก่อนแข็งตัวโดนแสง UV)", "hours", 50),
        ("Resin", "เช็ดคราบเรซิน/ฝุ่นที่แกน Z (Lead Screw) และทาจาระบีหรือน้ำมันหล่อลื่น PTFE ให้เลื่อนขึ้นลงสมูท", "hours", 200),
        ("Resin", "ตรวจสอบความใส/ความตึงแผ่นฟิล์ม FEP หรือ PFA — เปลี่ยนใหม่ถ้าขุ่นมัวมาก เป็นรอยลึก หรือย้วย", "hours", 200),
        ("Resin", "เป่าฝุ่นพัดลมใต้เครื่อง และเปลี่ยนแผ่นกรองคาร์บอน (Carbon Filter) ถ้าระบบกรองกลิ่นเริ่มทำงานได้ไม่ดี", "hours", 200),
        ("Resin", "ทดสอบแสง (Exposure Test) เพื่อเช็คจุดบอด (Dead Pixels) ของหน้าจอ LCD (จอ Monochrome อายุขัย ~2,000 ชม.)", "hours", 500),
        ("Resin", "ตรวจสอบและขันน็อต T-nut หรือน็อตยึดฐานพิมพ์และถังเรซินให้แน่น ป้องกันการขยับระหว่างชั้นเลเยอร์", "hours", 500),
    ]
    for device_type, task_name, interval_type, interval_value in new_plans:
        exists = conn.execute(
            "SELECT 1 FROM Maintenance_Plan_Items WHERE device_type=? AND task_name=?",
            (device_type, task_name),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO Maintenance_Plan_Items (device_type, task_name, interval_type, interval_value, is_active, created_at) "
                "VALUES (?,?,?,?,1,?)",
                (device_type, task_name, interval_type, interval_value, now()),
            )

    new_checklist = [
        ("Resin", "ฐานพิมพ์ (Build Plate): ขูดชิ้นงานออก และล้างทำความสะอาดด้วย IPA ให้หมดความมัน ก่อน-หลังพิมพ์ทุกครั้ง", 23),
        ("Resin", "ถังเรซิน (Resin Vat): ใช้ไม้พายซิลิโคนกวาดเบาๆ เช็คเศษชิ้นงานแข็งตกค้างติดแผ่นฟิล์ม (ห้ามใช้วัตถุแข็งขูดเด็ดขาด)", 24),
        ("Resin", "หากทิ้งเรซินไว้ในถังข้ามคืน ให้คนเรซินให้เข้ากันช้าๆ ก่อนพิมพ์ (ระวังอย่าให้เกิดฟองอากาศ)", 25),
        ("Resin", "ถ้าพิมพ์เสียครั้งก่อนหน้า: เทเรซินทั้งหมดผ่านกรวยกรองกลับลงขวดแล้ว เอาเศษเรซินแข็งออกให้หมด ป้องกันฟิล์ม/จอทะลุ", 26),
    ]
    for device_type, label, sort_order in new_checklist:
        exists = conn.execute(
            "SELECT 1 FROM Checklist_Items WHERE device_type=? AND label=?",
            (device_type, label),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO Checklist_Items (device_type, label, sort_order, is_active, created_at) VALUES (?,?,?,1,?)",
                (device_type, label, sort_order, now()),
            )


def _seed(conn: _Conn):
    # --- ลูกค้า (latitude/longitude ไม่บังคับ — ใส่ตัวอย่างไว้ให้เห็นบน Dashboard map ทันที) ---
    conn.execute(
        "INSERT INTO Customers (customer_id, name, phone, email, line_id, address, latitude, longitude) "
        "VALUES (1, 'คุณสมศรี ใจดี', '081-234-5678', 'somsri@example.com', 'somsri_line', '123 ถ.สุขุมวิท กรุงเทพฯ', 13.7360, 100.5600)"
    )
    conn.execute(
        "INSERT INTO Customers (customer_id, name, phone, email, line_id, address, latitude, longitude) "
        "VALUES (2, 'คุณอนันต์ พิมพ์ดี', '089-999-1234', 'anan@example.com', 'anan_line', '45 ถ.รัชดาภิเษก กรุงเทพฯ', 13.7800, 100.5750)"
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
    # ตัวอย่าง: สาขาสุขุมวิทรับซ่อมเฉพาะ FDM และจำหน่ายสินค้าด้วย, สาขารัชดารับซ่อมเฉพาะ Resin ไม่ขายสินค้า
    # (ตั้งต่างกันในข้อมูลตัวอย่างเพื่อให้เห็นสีที่ต่างกันบนแผนที่ทันที)
    conn.execute(
        "INSERT INTO Service_Centers (center_id, name, address, phone, latitude, longitude, supports_fdm, supports_resin, sells_products) "
        "VALUES (1, 'TD ServicePro สาขาสุขุมวิท', '123 ถ.สุขุมวิท กรุงเทพฯ', '02-111-2222', 13.7440, 100.5622, 1, 0, 1)"
    )
    conn.execute(
        "INSERT INTO Service_Centers (center_id, name, address, phone, latitude, longitude, supports_fdm, supports_resin, sells_products) "
        "VALUES (2, 'TD ServicePro สาขารัชดา', '45 ถ.รัชดาภิเษก กรุงเทพฯ', '02-333-4444', 13.7734, 100.5697, 0, 1, 0)"
    )

    # --- ผู้ใช้งาน (5 สิทธิ์) — center_id: ศูนย์บริการที่สังกัด (เฉพาะ staff)
    # phone: เบอร์โทรติดต่อของพนักงาน — ใช้แสดงบนหน้าแรกสาธารณะ (ผู้จัดการ/เซล) ---
    users = [
        ("admin1", "admin123", "admin", "แอดมิน สมชาย", "081-000-0001", None, 1),
        ("tech1", "tech123", "technician", "ช่างเอก", "081-000-0002", None, 1),
        ("tech2", "tech123", "technician", "ช่างบี", "081-000-0003", None, 2),
        ("mgr1", "mgr123", "manager", "ผจก. สมหญิง", "081-000-0004", None, 1),
        ("sale1", "sale123", "sales", "เซลล์ น้องฟ้า", "081-000-0005", None, 1),
        ("cust1", "cust123", "customer", "คุณสมศรี ใจดี", None, 1, None),
        ("cust2", "cust123", "customer", "คุณอนันต์ พิมพ์ดี", None, 2, None),
    ]
    for username, pwd, role, name, phone, customer_id, center_id in users:
        conn.execute(
            "INSERT INTO Users (username, password, role, name, phone, customer_id, center_id) VALUES (?,?,?,?,?,?,?)",
            (username, hash_password(pwd), role, name, phone, customer_id, center_id),
        )

    # --- คลังสินค้า (ค่าบริการเปลี่ยนอุปกรณ์มาตรฐาน + ค่าคอมมิชชั่น ต่อชิ้น + ศูนย์บริการที่เก็บสินค้า) ---
    parts = [
        ("NZ-04", "หัวฉีด 0.4mm", "Kobra 2, Kobra 3", 20, 150, 100, 20, 5, 1),
        ("LCD-MONO", "จอ LCD Mono", "Photon M5s, Photon Mono", 2, 2500, 300, 150, 3, 2),
        ("FEP-01", "แผ่น FEP", "Photon Series", 15, 300, 50, 30, 5, 2),
        ("MB-KOBRA2", "เมนบอร์ด Kobra 2", "Kobra 2", 1, 3200, 500, 200, 2, 1),
        ("BELT-01", "สายพาน GT2", "Kobra 2, Kobra 3", 10, 120, 100, 15, 4, 1),
    ]
    for sku, pname, models, qty, cost, labor, commission, reorder, center_id in parts:
        conn.execute(
            "INSERT INTO Spare_Parts (part_sku, part_name, compatible_models, stock_quantity, cost_price, labor_fee, commission_fee, reorder_level, center_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sku, pname, models, qty, cost, labor, commission, reorder, center_id),
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

    # --- ตัวอย่างการขายสินค้า (สาขาสุขุมวิท ซึ่ง sells_products=1) ---
    sale1_id = conn.execute("SELECT user_id FROM Users WHERE username='sale1'").fetchone()["user_id"]
    cur = conn.execute(
        "INSERT INTO Sales_Orders (center_id, sold_by, customer_id, created_at, notes) VALUES (1,?,?,?,?)",
        (sale1_id, 1, now(), "ลูกค้าซื้อหน้าร้าน"),
    )
    order_id = cur.lastrowid
    conn.execute(
        "INSERT INTO Sale_Items (order_id, part_sku, quantity, unit_price, commission_fee) VALUES (?,?,?,?,?)",
        (order_id, "NZ-04", 2, 180, 20),
    )
    conn.execute(
        "INSERT INTO Sale_Items (order_id, part_sku, quantity, unit_price, commission_fee) VALUES (?,?,?,?,?)",
        (order_id, "BELT-01", 1, 150, 15),
    )
    conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - 2 WHERE part_sku='NZ-04'")
    conn.execute("UPDATE Spare_Parts SET stock_quantity = stock_quantity - 1 WHERE part_sku='BELT-01'")
