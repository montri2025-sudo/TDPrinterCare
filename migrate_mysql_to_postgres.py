# -*- coding: utf-8 -*-
"""ย้ายข้อมูลจริงจาก MySQL (ระบบเดิม) มาที่ PostgreSQL (ระบบใหม่) — สคริปต์นี้รันครั้งเดียวตอน
cutover ไปใช้ PostgreSQL ใช้กับระบบที่ "ใช้งานจริงแล้ว" มีข้อมูลลูกค้า/ตั๋วซ่อม/ยอดขายค้างอยู่ ห้ามลบ
ฐานข้อมูล MySQL เดิมทิ้งจนกว่าจะตรวจสอบแล้วว่าข้อมูลใน PostgreSQL ครบถ้วนถูกต้อง 100%

=== ก่อนรันสคริปต์นี้ (ทำตามลำดับ) ===
  1. สำรองข้อมูล MySQL เดิมไว้ก่อนเสมอ (กันพลาด):
       docker exec tdprinter-mysql mysqldump -u root -p<รหัสผ่าน root> tdprinter_care > backup_before_migration.sql
  2. เตรียม container PostgreSQL ใหม่ให้พร้อมรับข้อมูล แต่ "ยังไม่ต้อง" ใส่บัญชีทดสอบ/ข้อมูลตัวอย่าง —
     ตั้ง SEED_DEMO_DATA=0 และเว้น INITIAL_ADMIN_USERNAME/PASSWORD ว่างไว้ก่อน แล้ว
     `docker compose up -d postgres tdprinter-care` หนึ่งรอบ เพื่อให้แอปสร้างตาราง (schema) เปล่าๆ
     ในฐานข้อมูล PostgreSQL ให้เรียบร้อยก่อน (สคริปต์นี้จะเรียก db.init_db() ให้เองอีกทีเผื่อยังไม่ได้ทำ)
  3. ต้องเชื่อมต่อได้ทั้ง MySQL เดิม (ที่ยังมีข้อมูลอยู่) และ PostgreSQL ใหม่พร้อมกัน — ถ้ารันสคริปต์นี้
     จากเครื่อง host (ไม่ใช่ในคอนเทนเนอร์) ให้เปิดพอร์ตทั้งสองฐานข้อมูลออกมาที่ 127.0.0.1 ชั่วคราว เช่น
     เพิ่ม `ports: ["3306:3306"]` ในคอนเทนเนอร์ mysql เดิม และ `ports: ["5432:5432"]` ในคอนเทนเนอร์
     postgres ใหม่ (เอาออกทีหลังหลัง migration เสร็จ เพื่อความปลอดภัย)
  4. ติดตั้งไลบรารีที่สคริปต์นี้ต้องใช้ (ทั้ง pymysql และ psycopg2 เพราะต้องคุยกับทั้งสองฐานข้อมูล):
       pip install pymysql psycopg2-binary

=== วิธีรัน ===
  ตั้งค่าฝั่ง MySQL ต้นทางผ่าน environment variables (ค่าเริ่มต้นชี้ไปที่ 127.0.0.1:3306 ตามที่เปิดไว้ในข้อ 3):
    SRC_MYSQL_HOST, SRC_MYSQL_PORT, SRC_MYSQL_USER, SRC_MYSQL_PASSWORD, SRC_MYSQL_DATABASE
  ฝั่ง PostgreSQL ปลายทางใช้ตัวแปรเดียวกับที่ app.py/db.py ใช้อยู่แล้ว (PG_HOST/PG_PORT/PG_USER/
  PG_PASSWORD/PG_DATABASE) — ตั้งให้ตรงกับ container postgres ใหม่

  ตัวอย่าง:
    SRC_MYSQL_HOST=127.0.0.1 SRC_MYSQL_USER=tdprinter SRC_MYSQL_PASSWORD=xxx SRC_MYSQL_DATABASE=tdprinter_care \\
    PG_HOST=127.0.0.1 PG_USER=tdprinter PG_PASSWORD=yyy PG_DATABASE=tdprinter_care \\
    python3 migrate_mysql_to_postgres.py

  สคริปต์จะถามยืนยันก่อนเขียนข้อมูลจริงเสมอ (พิมพ์ MIGRATE เพื่อยืนยัน) ใส่ --yes เพื่อข้ามการถามยืนยัน
  (ใช้ตอนรันอัตโนมัติ/ไม่มีคนคอยตอบเท่านั้น) และจะปฏิเสธไม่ทำงานถ้าฐานข้อมูล PostgreSQL ปลายทางมีข้อมูล
  อยู่แล้ว (กันรันซ้ำแล้วข้อมูลซ้ำซ้อน/ชนกัน) เว้นแต่จะใส่ --force

=== หลังรันสคริปต์นี้เสร็จ ===
  ตรวจสอบจำนวนแถวต่อตารางที่สคริปต์สรุปให้ท้ายรายงาน ต้องตรงกับ MySQL เดิมทุกตาราง แล้วเข้าระบบทดสอบ
  ผ่านหน้าเว็บจริงอีกรอบ (ล็อกอิน เปิดตั๋วซ่อมเก่า ดูรายงาน ฯลฯ) ก่อนจะเลิกใช้/ลบ MySQL เดิมทิ้ง
"""
import argparse
import os
import sys

import psycopg2

import db  # ใช้ PG_* env vars, get_conn(), init_db(), TABLE_PK, _reset_sequences() ตัวเดียวกับแอปจริง

SRC_MYSQL_HOST = os.environ.get("SRC_MYSQL_HOST", "127.0.0.1")
SRC_MYSQL_PORT = int(os.environ.get("SRC_MYSQL_PORT", "3306"))
SRC_MYSQL_USER = os.environ.get("SRC_MYSQL_USER", "tdprinter")
SRC_MYSQL_PASSWORD = os.environ.get("SRC_MYSQL_PASSWORD", "")
SRC_MYSQL_DATABASE = os.environ.get("SRC_MYSQL_DATABASE", "tdprinter_care")

# ลำดับตารางแบบเดียวกับ schema.sql เป๊ะๆ (FK-safe — ตารางแม่ต้องถูกโหลดข้อมูลก่อนตารางลูกเสมอ)
TABLE_ORDER = [
    "Service_Centers",
    "Customers",
    "Users",
    "Devices",
    "Maintenance_Plan_Items",
    "Checklist_Items",
    "Print_Sessions",
    "Maintenance_Logs",
    "Notifications",
    "Tickets",
    "Ticket_Media",
    "Spare_Parts",
    "Part_Images",
    "Service_Logs",
    "Payments",
    "Quotations",
    "Quotation_Items",
    "Sales_Orders",
    "Sale_Items",
    "Restock_Orders",
    "Restock_Order_Items",
    "Consignment_Settlements",
]

BATCH_COMMIT_EVERY = 500  # commit เป็นช่วงๆ ระหว่าง insert ตารางใหญ่ กันใช้ memory เยอะเกินไป/rollback ทีเดียวถ้าพัง


def _connect_mysql():
    import pymysql
    import pymysql.cursors
    if not SRC_MYSQL_PASSWORD:
        print("[error] ยังไม่ได้ตั้งค่า SRC_MYSQL_PASSWORD (รหัสผ่านฐานข้อมูล MySQL ต้นทาง) — ยกเลิก")
        sys.exit(1)
    return pymysql.connect(
        host=SRC_MYSQL_HOST, port=SRC_MYSQL_PORT,
        user=SRC_MYSQL_USER, password=SRC_MYSQL_PASSWORD,
        database=SRC_MYSQL_DATABASE, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _mysql_table_names(my_conn):
    with my_conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        return {list(row.values())[0].lower() for row in cur.fetchall()}


def _pg_row_count(pg_conn, table):
    return pg_conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]


def _mysql_row_count(my_conn, table):
    with my_conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM `{table}`")
        return cur.fetchone()["c"]


def _copy_table(my_conn, pg_conn, table):
    """คัดลอกข้อมูลทั้งหมดของตารางเดียวจาก MySQL ไป PostgreSQL โดยคงค่าคีย์หลัก (PK) เดิมทุกแถว
    (ไม่ปล่อยให้ SERIAL สร้างค่าใหม่) เพื่อรักษาความสัมพันธ์ foreign key ระหว่างตารางทั้งหมดให้ตรง
    กับของเดิมทุกจุด — ใช้ชื่อคอลัมน์ (ไม่ใช่ตำแหน่ง) ตอนสร้างคำสั่ง INSERT เพื่อความปลอดภัยแม้ลำดับ
    คอลัมน์ระหว่างสอง schema จะไม่ตรงกันเป๊ะ"""
    with my_conn.cursor() as cur:
        cur.execute(f"SELECT * FROM `{table}`")
        rows = cur.fetchall()

    if not rows:
        print(f"  [{table}] ไม่มีข้อมูล — ข้าม")
        return 0

    columns = list(rows[0].keys())
    placeholders = ",".join(["?"] * len(columns))
    col_list = ",".join(columns)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    inserted = 0
    try:
        for i, row in enumerate(rows, start=1):
            values = tuple(row[c] for c in columns)
            pg_conn.execute(sql, values)
            inserted += 1
            if i % BATCH_COMMIT_EVERY == 0:
                pg_conn.commit()
        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        print(f"  [{table}] !! ล้มเหลวที่แถวที่ {inserted + 1}/{len(rows)} — rollback ตารางนี้แล้ว")
        raise

    print(f"  [{table}] คัดลอกสำเร็จ {inserted} แถว")
    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="ข้ามการถามยืนยัน (ใช้ตอนรันอัตโนมัติเท่านั้น)")
    parser.add_argument("--force", action="store_true",
                         help="ยอมให้รันแม้ฐานข้อมูล PostgreSQL ปลายทางจะมีข้อมูลอยู่แล้ว (ปกติสคริปต์จะปฏิเสธ กันข้อมูลซ้ำซ้อน)")
    args = parser.parse_args()

    print("=" * 78)
    print("ย้ายข้อมูลจาก MySQL -> PostgreSQL (TD ServicePro)")
    print(f"  ต้นทาง (MySQL):      {SRC_MYSQL_USER}@{SRC_MYSQL_HOST}:{SRC_MYSQL_PORT}/{SRC_MYSQL_DATABASE}")
    print(f"  ปลายทาง (PostgreSQL): {db.PG_USER}@{db.PG_HOST}:{db.PG_PORT}/{db.PG_DATABASE}")
    print("=" * 78)
    print("คำเตือน: สคริปต์นี้จะเขียนข้อมูลลงฐานข้อมูล PostgreSQL ปลายทางโดยตรง กรุณาสำรองข้อมูล MySQL")
    print("ต้นทางไว้ก่อนเสมอ (ดูวิธีในคอมเมนต์ต้นไฟล์นี้) และตรวจสอบให้แน่ใจว่าปลายทางตั้งค่าถูกต้อง")
    print("=" * 78)

    if not args.yes:
        answer = input("พิมพ์ MIGRATE (ตัวพิมพ์ใหญ่) เพื่อยืนยันว่าต้องการดำเนินการต่อ: ").strip()
        if answer != "MIGRATE":
            print("ยกเลิก — ไม่มีข้อมูลใดถูกเขียน")
            sys.exit(1)

    # 1) เตรียม schema ฝั่ง PostgreSQL ให้พร้อม (สร้างตารางถ้ายังไม่มี) — บังคับปิดการ seed ข้อมูล
    # ตัวอย่าง/บัญชีทดสอบไว้ชั่วคราวระหว่างสคริปต์นี้ทำงาน กันชนกับข้อมูลจริงที่กำลังจะนำเข้ามา
    db.SEED_DEMO_DATA = False
    db.INITIAL_ADMIN_USERNAME = None
    db.INITIAL_ADMIN_PASSWORD = None
    print("\n[1/4] เตรียม schema ฝั่ง PostgreSQL...")
    db.init_db()

    pg_conn = db.get_conn()

    # 2) เช็คว่าฐานข้อมูลปลายทางว่างจริง (กันรันซ้ำแล้วข้อมูลซ้ำซ้อน/ชนคีย์หลัก)
    existing_users = _pg_row_count(pg_conn, "Users")
    if existing_users > 0 and not args.force:
        print(f"\n[error] ฐานข้อมูล PostgreSQL ปลายทางมีข้อมูลอยู่แล้ว (Users {existing_users} แถว) —")
        print("        ยกเลิกเพื่อกันข้อมูลซ้ำซ้อน/ชนคีย์หลัก ถ้าตั้งใจจะรันทับจริงๆ ใส่ --force")
        pg_conn.close()
        sys.exit(1)

    # 2.5) db.init_db() ด้านบนใส่ "แผนบำรุงรักษา/checklist เริ่มต้นของระบบ" ให้อัตโนมัติถ้าสองตารางนี้
    # ว่าง (เป็นค่าตั้งต้นของระบบ ไม่ผูกกับ SEED_DEMO_DATA — ดู _migrate_schema() ใน db.py) ซึ่งจะไปชน
    # กับ plan_item_id/checklist_item_id จริงที่กำลังจะ copy มาจาก MySQL (เริ่มที่เลข 1 เหมือนกัน) —
    # ล้างข้อมูลที่เพิ่ง auto-seed ไปทิ้งก่อน เพื่อให้ข้อมูลจริงจาก MySQL เป็นเจ้าของ ID ชุดนี้แต่เพียง
    # ผู้เดียว ปลอดภัยที่จะลบตรงนี้เพราะยังไม่มีตารางลูกใดๆ (Maintenance_Logs/Notifications) ที่ถูก
    # copy เข้ามาอ้างอิงอยู่เลยในจังหวะนี้
    pg_conn.execute("DELETE FROM Maintenance_Plan_Items")
    pg_conn.execute("DELETE FROM Checklist_Items")
    pg_conn.commit()

    # 3) เชื่อมต่อ MySQL ต้นทาง แล้วคัดลอกข้อมูลทีละตารางตามลำดับ FK-safe
    print("\n[2/4] เชื่อมต่อ MySQL ต้นทาง...")
    my_conn = _connect_mysql()
    mysql_tables = _mysql_table_names(my_conn)

    print("\n[3/4] คัดลอกข้อมูล...")
    counts = {}
    for table in TABLE_ORDER:
        if table.lower() not in mysql_tables:
            print(f"  [{table}] ไม่พบตารางนี้ใน MySQL ต้นทาง — ข้าม (อาจเป็นตารางที่เพิ่งเพิ่มใหม่ยังไม่มีข้อมูลเก่า)")
            continue
        counts[table] = _copy_table(my_conn, pg_conn, table)

    my_conn.close()

    # 4) รีเซ็ต SERIAL sequence ทุกตารางให้ตรงกับ MAX(id) ปัจจุบัน — จำเป็นเพราะเราเพิ่งใส่ค่า PK
    # เองตรงๆ ทุกแถว (Postgres ไม่ขยับ sequence ให้อัตโนมัติแบบที่ MySQL ทำให้ตอน insert ระบุ PK เอง)
    print("\n[4/4] รีเซ็ต SERIAL sequence ให้ตรงกับข้อมูลที่เพิ่งนำเข้า...")
    db._reset_sequences(pg_conn)
    print("  เรียบร้อย")

    # สรุปผล + ตรวจนับแถวเทียบ MySQL ต้นทางอีกรอบ (เปิดการเชื่อมต่อ MySQL ใหม่เพราะปิดไปแล้วด้านบน)
    print("\n" + "=" * 78)
    print("สรุปผลการย้ายข้อมูล (จำนวนแถว: MySQL ต้นทาง -> PostgreSQL ปลายทาง)")
    print("=" * 78)
    my_conn = _connect_mysql()
    all_match = True
    for table in TABLE_ORDER:
        if table.lower() not in mysql_tables:
            continue
        src_count = _mysql_row_count(my_conn, table)
        dst_count = _pg_row_count(pg_conn, table)
        flag = "OK" if src_count == dst_count else "!! ไม่ตรงกัน !!"
        if src_count != dst_count:
            all_match = False
        print(f"  {table:28s} {src_count:>8d}  ->  {dst_count:>8d}   {flag}")
    my_conn.close()
    pg_conn.close()

    print("=" * 78)
    if all_match:
        print("จำนวนแถวตรงกันทุกตาราง — ย้ายข้อมูลสำเร็จ")
        print("ก่อนเลิกใช้/ลบฐานข้อมูล MySQL เดิม กรุณาทดสอบเข้าระบบผ่านหน้าเว็บจริงอีกรอบให้แน่ใจก่อน")
        print("(ล็อกอินทุกสิทธิ์, เปิดตั๋วซ่อมเก่า, ดูรายงาน, ตรวจสอบยอดขาย/สต็อกสินค้า ฯลฯ)")
    else:
        print("!! พบตารางที่จำนวนแถวไม่ตรงกัน — ห้ามใช้งานระบบใหม่จนกว่าจะตรวจสอบสาเหตุให้แน่ใจก่อน !!")
        sys.exit(1)


if __name__ == "__main__":
    main()
