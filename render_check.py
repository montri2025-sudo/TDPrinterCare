import sys, re
from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
env.globals["asset_v"] = lambda name: 0  # mock ของ app.py::_asset_version สำหรับทดสอบ render เฉยๆ ไม่ต้องอ่านไฟล์จริง

STATUSES = ["New", "Diagnosing", "Waiting for Parts", "In Repair", "Testing", "Resolved/Closed"]
STATUS_LABELS = {
    "New": "รอซ่อม",
    "Diagnosing": "กำลังตรวจสอบ",
    "Waiting for Parts": "รออะไหล่",
    "In Repair": "กำลังซ่อม",
    "Testing": "ทดสอบ",
    "Resolved/Closed": "เรียบร้อยแล้ว",
}
STATUS_INDEX = {s: i for i, s in enumerate(STATUSES)}
STATUS_ICONS = {
    "New": "🆕", "Diagnosing": "🔍", "Waiting for Parts": "⏳",
    "In Repair": "🔧", "Testing": "🧪", "Resolved/Closed": "✅",
}

# หมายเหตุสำคัญ: statuses/status_labels/status_icons/csrf_token/unread_notif_count คือ 5 คีย์ที่
# app.py::render() ฉีดให้ "ทุกเทมเพลตโดยอัตโนมัติ" อยู่แล้ว (ดู def render() ใน app.py) — ถ้า route ไหน
# เผลอส่งคีย์ชื่อซ้ำกันนี้เข้ามาเองด้วย (เช่นบั๊กที่เจอจริง: ส่ง status_labels=RESTOCK_STATUS_LABELS ทับ)
# จะเกิด "TypeError: got multiple values for keyword argument" ตอน production จริง — ของเดิมที่เคย
# ใส่ 5 คีย์นี้ปนอยู่ใน BASE dict() เฉยๆ จะ "silently overwrite" กันเองไม่ error ทำให้ render_check.py
# ตรวจไม่เจอบั๊กแบบนี้เลย จึงแยก RENDER_DEFAULTS ออกมาต่างหาก แล้วจำลองการ merge แบบเดียวกับ
# app.py::render() เป๊ะๆ ตรงจุด tmpl.render(**RENDER_DEFAULTS, **ctx) ด้านล่าง เพื่อให้ Python เอง
# เป็นคน raise TypeError ให้เหมือนของจริงถ้ามีคีย์ชนกันอีกในอนาคต
RENDER_DEFAULTS = dict(statuses=STATUSES, status_labels=STATUS_LABELS, status_icons=STATUS_ICONS,
                        csrf_token="test-csrf-token", unread_notif_count=2)

BASE = dict(status_index=STATUS_INDEX)

DEVICE_TYPES = ["FDM", "Resin", "Wash & Cure", "Other"]
MAINTENANCE_INTERVAL_TYPE_LABELS = {"days": "วัน", "hours": "ชั่วโมง"}

user_admin = {"user_id": 1, "role": "admin", "name": "แอดมิน สมชาย", "center_id": None}
user_manager = {"user_id": 4, "role": "manager", "name": "ผจก. สมหญิง", "center_id": 1}
user_sales = {"user_id": 5, "role": "sales", "name": "เซลล์ น้องฟ้า", "center_id": 1}
user_tech = {"user_id": 2, "role": "technician", "name": "ช่างเอก", "center_id": 1}
user_customer = {"user_id": 6, "role": "customer", "name": "คุณสมศรี ใจดี", "customer_id": 1, "center_id": None}

center = {"center_id": 1, "name": "TDprinter Partner สาขาสุขุมวิท", "address": "123 ถ.สุขุมวิท", "phone": "02-000-1111",
          "marker_color": "#2e5395", "type_label": "FDM เท่านั้น", "sells_products": 1, "latitude": 13.736, "longitude": 100.56,
          "popup_html": "<b>TDprinter Partner สาขาสุขุมวิท</b><br>คิวงาน: 2 รายการ"}
center2 = dict(center, center_id=2, name="TDprinter Partner สาขารัชดา", sells_products=0, latitude=13.78, longitude=100.575,
               popup_html="<b>TDprinter Partner สาขารัชดา</b><br>ไม่มีงานในคิวขณะนี้")

ticket = {"ticket_id": 101, "status": "In Repair", "issue_category": "หัวพิมพ์อุดตัน", "model": "Kobra 2",
          "device_sn": "AC-KOBRA2-0001", "device_type": "FDM", "device_total_usage_hours": 180.0,
          "center_id": 1, "center_name": center["name"], "description": "อาการ...",
          "created_at": "2026-07-01 10:00:00", "closed_at": None, "csat_score": None, "csat_comment": None}
ticket_closed = dict(ticket, ticket_id=102, status="Resolved/Closed", closed_at="2026-07-05 15:00:00", csat_score=5, csat_comment="ดีมาก")

device = {"device_sn": "AC-KOBRA2-0001", "model": "Kobra 2", "customer_id": 1, "status": "Active"}
device_full = dict(device, type="FDM", warranty_end_date="2026-12-01", last_maintenance="2026-06-15")
device_never_maintained = dict(device, device_sn="AC-KOBRA2-0002", model="Kobra 3",
                                type="Resin", warranty_end_date=None, status="Decommissioned", last_maintenance=None)

def days_left_test(warranty_end_date):
    if not warranty_end_date:
        return None
    return 30

customer = {"customer_id": 1, "name": "คุณสมศรี ใจดี", "phone": "081-111-2222", "email": "s@x.com", "line_id": "somsri",
            "address": "45 ถ.สุขุมวิท", "tax_id": "1234567890123", "latitude": 13.736, "longitude": 100.56, "device_count": 2,
            "device_quota": 3, "popup_html": "<b>คุณสมศรี ใจดี</b><br>เครื่องพิมพ์ทั้งหมด: 2 เครื่อง"}
customer2 = dict(customer, customer_id=2, name="คุณอนันต์ พิมพ์ดี", tax_id=None, latitude=13.78, longitude=100.575, device_count=1,
                  device_quota=1, popup_html="<b>คุณอนันต์ พิมพ์ดี</b><br>เครื่องพิมพ์ทั้งหมด: 1 เครื่อง")

# --- Maintenance Scheduler / Checklist / Print Sessions / History / Notifications ---
maint_device = dict(device_full, total_usage_hours=180.0, customer_name=customer["name"])
maint_device_ready = dict(device_full, device_sn="AC-KOBRA2-0003", model="Kobra 3", total_usage_hours=20.0,
                           customer_name=customer["name"])

plan_item_days = {"plan_item_id": 1, "device_type": None, "task_name": "ทำความสะอาดทั่วไป (ตัวเครื่อง/พัดลม/ราง)",
                   "interval_type": "days", "interval_value": 7, "is_active": 1, "created_at": "2026-01-01 00:00:00"}
plan_item_hours = {"plan_item_id": 2, "device_type": "FDM", "task_name": "ทาจาระบีแกน X/Y/Z",
                    "interval_type": "hours", "interval_value": 200, "is_active": 1, "created_at": "2026-01-01 00:00:00"}
plan_item_inactive = dict(plan_item_hours, plan_item_id=3, task_name="เปลี่ยนหัวฉีด (Nozzle)", interval_value=500, is_active=0)

due_task_days = {"plan_item_id": 1, "task_name": plan_item_days["task_name"], "device_type": None,
                  "interval_type": "days", "interval_value": 7, "last_done_at": None, "last_done_hours": None,
                  "due": True, "overdue_label": "ยังไม่เคยทำ"}
due_task_hours = {"plan_item_id": 2, "task_name": plan_item_hours["task_name"], "device_type": "FDM",
                   "interval_type": "hours", "interval_value": 200, "last_done_at": "2026-06-01", "last_done_hours": 0.0,
                   "due": True, "overdue_label": "ใช้งานสะสม 180 ชม. (เกินรอบ 200 ชม. ไป -20 ชม.)"}
not_due_task = {"plan_item_id": 4, "task_name": "ตรวจสอบเส้นพลาสติกเพียงพอ", "device_type": None,
                 "interval_type": "days", "interval_value": 30, "last_done_at": "2026-07-10", "last_done_hours": None,
                 "due": False, "overdue_label": None}

overview_maintenance_due = {"status": "maintenance_due", "open_ticket_id": None,
                             "tasks": [due_task_days, due_task_hours, not_due_task], "due_tasks": [due_task_days, due_task_hours]}
overview_ready = {"status": "ready", "open_ticket_id": None, "tasks": [not_due_task], "due_tasks": []}
overview_in_repair = {"status": "in_repair", "open_ticket_id": 101, "tasks": [], "due_tasks": []}

checklist_item1 = {"checklist_item_id": 1, "device_type": None, "label": "ตรวจสอบพื้นที่รอบเครื่องปลอดภัย ไม่มีวัสดุไวไฟใกล้เครื่อง",
                    "sort_order": 1, "is_active": 1, "created_at": "2026-01-01 00:00:00"}
checklist_item2 = {"checklist_item_id": 2, "device_type": "FDM", "label": "ทำความสะอาดฐานพิมพ์ (Bed) ให้ปราศจากคราบ/เศษพลาสติก",
                    "sort_order": 10, "is_active": 1, "created_at": "2026-01-01 00:00:00"}
checklist_item_inactive = dict(checklist_item1, checklist_item_id=3, label="ตรวจสอบเก่า (ปิดใช้งานแล้ว)", is_active=0)

maint_log1 = {"maintenance_id": 1, "device_sn": maint_device["device_sn"], "plan_item_id": 2,
              "task_name": plan_item_hours["task_name"], "performed_at": "2026-06-01",
              "hours_at_maintenance": 0.0, "parts_replaced": None, "notes": "ทาจาระบีตามรอบ",
              "performed_by": 1, "performed_by_name": user_admin["name"]}
maint_log2 = {"maintenance_id": 2, "device_sn": maint_device["device_sn"], "plan_item_id": None,
              "task_name": None, "performed_at": "2026-07-01", "hours_at_maintenance": 150.0,
              "parts_replaced": "หัวฉีด 0.4mm", "notes": "เปลี่ยนหัวฉีดใหม่ (บันทึกอิสระ)",
              "performed_by": 6, "performed_by_name": user_customer["name"]}

print_session1 = {"session_id": 1, "device_sn": maint_device["device_sn"], "started_by": 6,
                   "checklist": [checklist_item1["label"], checklist_item2["label"]],
                   "estimated_hours": 3.5, "job_note": "พิมพ์ชิ้นงานตัวอย่าง", "created_at": "2026-07-20 09:00:00",
                   "started_by_name": user_customer["name"]}
print_session2 = dict(print_session1, session_id=2, checklist=[], estimated_hours=0, job_note="",
                       created_at="2026-07-21 10:00:00")

notif_unread = {"notification_id": 1, "user_id": 6, "device_sn": maint_device["device_sn"], "plan_item_id": 2,
                 "category": "maintenance_due", "title": "🔧 ถึงรอบบำรุงรักษา: Kobra 2 (AC-KOBRA2-0001)",
                 "message": "งาน 'ทาจาระบีแกน X/Y/Z' — ใช้งานสะสม 180 ชม.", "is_read": 0,
                 "email_sent": 1, "email_error": None, "created_at": "2026-07-25 08:00:00", "model": "Kobra 2"}
notif_read = dict(notif_unread, notification_id=2, is_read=1, email_sent=0,
                   email_error="SMTP ยังไม่ได้ตั้งค่า (SMTP_HOST ว่าง) — ข้ามการส่งอีเมล")

PRODUCT_CATEGORIES = ["FDM_Printer", "Resin_Printer", "Spare_Part", "Material", "Other"]
PRODUCT_CATEGORY_LABELS = {
    "FDM_Printer": "เครื่องพิมพ์ FDM", "Resin_Printer": "เครื่องพิมพ์ Resin",
    "Spare_Part": "อะไหล่", "Material": "วัสดุพิมพ์", "Other": "อื่นๆ",
}
PRODUCT_CATEGORY_ICONS = {
    "FDM_Printer": "🖨️", "Resin_Printer": "🧪", "Spare_Part": "🔧", "Material": "🧵", "Other": "📦",
}

part = {"part_sku": "NZ-04", "part_name": "หัวฉีด 0.4mm", "stock_quantity": 20, "cost_price": 150.0,
        "commission_fee": 10.0, "center_id": 1, "reorder_level": 5, "labor_fee": 100.0, "category": "Spare_Part",
        "image_filename": None, "description": None, "images": [], "gallery": [], "gallery_slots_left": 9,
        "ownership": "owned"}
part2 = dict(part, part_sku="BLT-01", part_name="สายพาน X-axis", stock_quantity=5, category="Material",
             description="สายพานไทม์มิ่ง GT2 ยาว 6 เมตร เข้ากันได้กับเครื่องพิมพ์ 3 มิติทั่วไป",
             gallery=[{"image_id": 1, "stored_name": "demo-belt-2.jpg"}], images=["demo-belt-2.jpg"],
             gallery_slots_left=8, ownership="consignment")
part_printer = dict(part, part_sku="PR-K2", part_name="Kobra 2", stock_quantity=3, category="FDM_Printer",
                     image_filename="demo-printer.jpg", description=None,
                     gallery=[{"image_id": 2, "stored_name": "demo-printer-2.jpg"},
                              {"image_id": 3, "stored_name": "demo-printer-3.jpg"}],
                     images=["demo-printer.jpg", "demo-printer-2.jpg", "demo-printer-3.jpg"],
                     gallery_slots_left=6)

sale_order = {"order_id": 1, "created_at": "2026-07-10 09:00:00", "total_amount": 1500.0, "center_id": 1,
              "center_name": center["name"], "customer_id": 1, "customer_name": customer["name"],
              "sold_by_name": user_sales["name"], "notes": None}
sale_item = {"item_id": 1, "order_id": 1, "part_sku": "NZ-04", "part_name": part["part_name"], "quantity": 2,
             "unit_price": 150.0, "line_total": 300.0, "commission_fee": 10.0}

quote = {"quote_id": 1, "created_at": "2026-07-02 10:00:00", "notes": "ประเมินเบื้องต้น", "total": 500.0,
         "line_items": [{"description": "ค่าแรง", "quantity": 1, "unit_price": 500.0, "tech_notes": "พบปัญหาที่หัวฉีด"}]}

invoice_items = [{"created_at": "2026-07-05", "action": "เปลี่ยนหัวฉีด", "part_name": "หัวฉีด 0.4mm",
                   "part_cost": 150.0, "labor_fee": 200.0, "line_total": 350.0, "tech_notes": "พบปัญหาที่หัวฉีด", "is_claim": False},
                  {"created_at": "2026-07-05", "action": "เปลี่ยนสายพาน (เคลมประกัน)", "part_name": "สายพาน X-axis",
                   "part_cost": 0.0, "labor_fee": 100.0, "line_total": 100.0, "tech_notes": None, "is_claim": True}]

log = {"log_id": 1, "created_at": "2026-07-03 11:00:00", "action_taken": "ตรวจสอบเบื้องต้น", "tech_notes": "พบปัญหาที่หัวฉีด",
       "labor_fee": 100.0, "part_sku_used": "NZ-04", "quantity_used": 1, "approval_status": "auto", "is_claim": False}
log_claim = dict(log, log_id=2, action_taken="เปลี่ยนสายพาน (เคลมประกัน)", part_sku_used="BLT-01", is_claim=True)

payment_confirmed = {"payment_id": 1, "ticket_id": 102, "amount": 350.0, "slip_filename": "slip_demo.jpg",
                      "notified_by": 6, "notified_by_name": customer["name"], "status": "confirmed",
                      "confirmed_by": 1, "confirmed_by_name": user_admin["name"], "confirmed_at": "2026-07-06 09:00:00",
                      "created_at": "2026-07-05 16:00:00", "notes": None}
payment_pending = dict(payment_confirmed, payment_id=2, status="pending", confirmed_by=None,
                        confirmed_by_name=None, confirmed_at=None, notes="โอนผ่านพร้อมเพย์")
payments = [payment_pending, payment_confirmed]

overview = {
    1: {"managers": [{"name": user_manager["name"]}],
        "sales_people": [{"name": user_sales["name"]}],
        "technicians": [{"name": "ช่างเอก"}, {"name": "ช่างบี"}],
        "queue": [ticket],
        "parts": [part2, part_printer],
        "parts_by_category": [
            {"category": "FDM_Printer", "label": PRODUCT_CATEGORY_LABELS["FDM_Printer"], "parts": [part_printer]},
            {"category": "Material", "label": PRODUCT_CATEGORY_LABELS["Material"], "parts": [part2]},
        ]},
    2: {"managers": [], "sales_people": [], "technicians": [], "queue": [], "parts": [], "parts_by_category": []},
}

DEVICE_STATUS_LABELS_TEST = {"Active": "ใช้งานอยู่", "Decommissioned": "เลิกใช้แล้ว", "Sold": "ขายต่อแล้ว"}

CONTEXTS = {
    "login.html": dict(BASE, error=None, google_ready=True, line_ready=True),
    "signup.html": dict(BASE, google_ready=True, line_ready=False),
    "signup_complete.html": dict(BASE, token="tok-abc123",
                                  pending={"provider": "google", "sub": "10987654321", "name": "คุณทดสอบ ระบบ", "email": "test@example.com"},
                                  error=None),
    "customer_device_new.html": dict(BASE, user=user_customer, welcome=True, just_added=False, device_count=1,
                                       quota=3, quota_reached=False,
                                       my_devices=[dict(device_full, status="Active", purchase_proof_filename="proof_ab12cd34_receipt.jpg"),
                                                   dict(device_full, device_sn="AC-KOBRA2-0009", status="Active", purchase_proof_filename=None)],
                                       device_status_labels=DEVICE_STATUS_LABELS_TEST, error=None, max_device_proof_mb=5),
    "home.html": dict(BASE, centers=[center, center2], centers_with_geo=[center, center2], overview=overview,
                        category_icons=PRODUCT_CATEGORY_ICONS,
                        centers_contact_for_js=[
                            {"id": center["center_id"], "name": center["name"], "phone": center["phone"], "address": center["address"]},
                            {"id": center2["center_id"], "name": center2["name"], "phone": center2["phone"], "address": center2["address"]},
                        ]),
    "track.html": dict(BASE, sn="AC-KOBRA2-0001", device=device, tickets=[ticket, ticket_closed]),
    "admin_dashboard.html": dict(BASE, user=user_admin, counts={"New": 12, "Diagnosing": 8, "Waiting for Parts": 2, "In Repair": 15, "Testing": 1, "Resolved/Closed": 20},
                                   total=58,
                                   workload=[{"name": "ช่างเอก", "open_count": 3, "open_tickets": 3}], low_stock=[part2],
                                   low_stock_by_category=[
                                       {"category": "Material", "label": PRODUCT_CATEGORY_LABELS["Material"],
                                        "icon": PRODUCT_CATEGORY_ICONS["Material"], "parts": [dict(part2, center_name=center["name"])]},
                                       {"category": "FDM_Printer", "label": PRODUCT_CATEGORY_LABELS["FDM_Printer"],
                                        "icon": PRODUCT_CATEGORY_ICONS["FDM_Printer"], "parts": [dict(part_printer, center_name=None)]},
                                   ],
                                   centers=[center, center2], centers_with_geo=[center, center2],
                                   customers_with_geo=[customer, customer2], scope_label=None,
                                   maintenance_due=[
                                       {"device_sn": maint_device["device_sn"], "model": maint_device["model"],
                                        "customer_name": customer["name"], "due_tasks": [due_task_days, due_task_hours],
                                        "due_count": 2},
                                       {"device_sn": "AC-KOBRA2-0004", "model": "Kobra 3", "customer_name": customer2["name"],
                                        "due_tasks": [due_task_days], "due_count": 1},
                                   ],
                                   dash_chart_labels=["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"],
                                   dash_chart_fdm=[10000, 12000, 8000, 15000, 9000, 11000],
                                   dash_chart_resin=[3000, 4000, 2000, 5000, 3500, 4200],
                                   dash_chart_material=[1500, 1800, 1200, 2000, 1700, 1900],
                                   dash_chart_tickets_created=[5, 8, 6, 9, 7, 10],
                                   dash_chart_tickets_closed=[4, 7, 6, 8, 6, 9],
                                   dash_chart_labor=[2000, 2500, 1800, 3000, 2200, 2700],
                                   dash_cases_for_js={
                                       "New": [{"ticket_id": 101, "model": "Kobra 2", "customer_name": customer["name"],
                                                 "status": "New", "status_label": "รอซ่อม", "date": "2026-07-20 09:00:00"}],
                                       "Diagnosing": [], "Waiting for Parts": [], "In Repair": [
                                           {"ticket_id": 101, "model": "Kobra 2", "customer_name": customer["name"],
                                            "status": "In Repair", "status_label": "กำลังซ่อม", "date": "2026-07-01 10:00:00"}],
                                       "Testing": [], "Resolved/Closed": [
                                           {"ticket_id": 102, "model": "Kobra 2", "customer_name": customer2["name"],
                                            "status": "Resolved/Closed", "status_label": "เรียบร้อยแล้ว", "date": "2026-07-05 15:00:00"}],
                                       "total": [
                                           {"ticket_id": 101, "model": "Kobra 2", "customer_name": customer["name"],
                                            "status": "In Repair", "status_label": "กำลังซ่อม", "date": "2026-07-01 10:00:00"},
                                           {"ticket_id": 102, "model": "Kobra 2", "customer_name": customer2["name"],
                                            "status": "Resolved/Closed", "status_label": "เรียบร้อยแล้ว", "date": "2026-07-05 15:00:00"},
                                       ],
                                   },
                                   pending_payments_count=8,
                                   pending_payments_for_js=[
                                       {"ticket_id": 102, "payment_id": 2, "model": "Kobra 2", "customer_name": customer["name"],
                                        "amount": 350.0, "slip_url": "/media/102/slip_demo.jpg", "date": "2026-07-05 16:00:00"},
                                   ]),
    "admin_board.html": dict(BASE, user=user_admin, board={s: [ticket] if s == "In Repair" else [] for s in STATUSES},
                               techs=[{"user_id": 2, "name": "ช่างเอก"}], date_from="2026-07-01", date_to="2026-07-31"),
    "admin_ticket_detail.html": dict(BASE, user=user_admin, t=ticket_closed, media=[], logs=[log, log_claim], quotes=[quote],
                                       invoice_items=invoice_items, invoice_total=350.0, technicians=[{"user_id": 2, "name": "ช่างเอก"}],
                                       parts=[part, part2], payments=payments),
    "admin_customers.html": dict(BASE, user=user_admin, customers=[customer, customer2],
                                   devices=[device_full, device_never_maintained],
                                   days_left=days_left_test, today="2026-07-23",
                                   customers_for_js=[
                                       {"id": customer["customer_id"], "name": customer["name"], "phone": customer["phone"], "tax_id": customer["tax_id"]},
                                       {"id": customer2["customer_id"], "name": customer2["name"], "phone": customer2["phone"], "tax_id": ""},
                                   ]),
    "admin_new_ticket.html": dict(BASE, user=user_admin, error=None,
                                    max_images=10, max_video_mb=10,
                                    customers=[customer, customer2],
                                    customers_for_js=[
                                        {"id": customer["customer_id"], "name": customer["name"], "phone": customer["phone"], "tax_id": customer["tax_id"]},
                                        {"id": customer2["customer_id"], "name": customer2["name"], "phone": customer2["phone"], "tax_id": ""},
                                    ],
                                    devices_by_customer_for_js={
                                        customer["customer_id"]: [{"sn": device_full["device_sn"], "model": device_full["model"], "has_open_ticket": False}],
                                        customer2["customer_id"]: [],
                                    },
                                    repair_centers=[center, center2], fixed_center=None, blocked_reason=None),
    "admin_centers.html": dict(BASE, user=user_admin, centers=[center, center2]),
    "customer_maintenance.html": dict(BASE, user=user_customer,
                                        devices=[dict(maint_device, overview=overview_maintenance_due),
                                                 dict(maint_device_ready, overview=overview_ready)],
                                        summary={"ready": 1, "maintenance_due": 1, "in_repair": 0},
                                        device_type_labels={"FDM": "FDM", "Resin": "Resin", "Wash & Cure": "Wash & Cure", "Other": "อื่นๆ"}),
    "customer_dashboard.html": dict(BASE, user=user_customer,
                                      counts={"New": 1, "Diagnosing": 0, "Waiting for Parts": 0, "In Repair": 1, "Testing": 0, "Resolved/Closed": 1},
                                      total=3,
                                      customer_cases_for_js={
                                          "New": [{"ticket_id": 103, "model": "Kobra 3", "status": "New", "status_label": "รอซ่อม", "date": "2026-07-20 09:00:00"}],
                                          "Diagnosing": [], "Waiting for Parts": [],
                                          "In Repair": [{"ticket_id": 101, "model": "Kobra 2", "status": "In Repair", "status_label": "กำลังซ่อม", "date": "2026-07-01 10:00:00"}],
                                          "Testing": [],
                                          "Resolved/Closed": [{"ticket_id": 102, "model": "Kobra 2", "status": "Resolved/Closed", "status_label": "เรียบร้อยแล้ว", "date": "2026-07-05 15:00:00"}],
                                          "total": [
                                              {"ticket_id": 103, "model": "Kobra 3", "status": "New", "status_label": "รอซ่อม", "date": "2026-07-20 09:00:00"},
                                              {"ticket_id": 101, "model": "Kobra 2", "status": "In Repair", "status_label": "กำลังซ่อม", "date": "2026-07-01 10:00:00"},
                                              {"ticket_id": 102, "model": "Kobra 2", "status": "Resolved/Closed", "status_label": "เรียบร้อยแล้ว", "date": "2026-07-05 15:00:00"},
                                          ],
                                      },
                                      summary={"ready": 1, "maintenance_due": 1, "in_repair": 1, "decommissioned": 1, "sold": 1},
                                      customer_devices_for_js={
                                          "ready": [{"device_sn": maint_device_ready["device_sn"], "model": maint_device_ready["model"],
                                                     "total_usage_hours": maint_device_ready["total_usage_hours"], "open_ticket_id": None, "due_tasks": []}],
                                          "maintenance_due": [{"device_sn": maint_device["device_sn"], "model": maint_device["model"],
                                                                "total_usage_hours": maint_device["total_usage_hours"], "open_ticket_id": None,
                                                                "due_tasks": ["ทาจาระบีแกน X/Y/Z — ใช้งานสะสม 180 ชม. (เกินรอบ 200 ชม. ไป -20 ชม.)"]}],
                                          "in_repair": [{"device_sn": "AC-KOBRA2-0004", "model": "Kobra 3", "total_usage_hours": 90.0,
                                                          "open_ticket_id": 101, "due_tasks": []}],
                                          "decommissioned": [{"device_sn": "AC-KOBRA2-0005", "model": "Kobra 2 (เก่า)", "total_usage_hours": 2000.0,
                                                                "open_ticket_id": None, "due_tasks": []}],
                                          "sold": [{"device_sn": "AC-KOBRA2-0006", "model": "Kobra 3 (ขายแล้ว)", "total_usage_hours": 500.0,
                                                     "open_ticket_id": None, "due_tasks": []}],
                                      },
                                      device_type_labels={"FDM": "FDM", "Resin": "Resin", "Wash & Cure": "Wash & Cure", "Other": "อื่นๆ"},
                                      type_counts={"FDM": 2, "Resin": 0, "Wash & Cure": 0, "Other": 0},
                                      customer_devices_by_type_for_js={
                                          "FDM": [
                                              {"device_sn": maint_device["device_sn"], "model": maint_device["model"],
                                               "total_usage_hours": maint_device["total_usage_hours"], "status": "maintenance_due", "status_label": "🛠️ ถึงรอบบำรุงรักษา"},
                                              {"device_sn": maint_device_ready["device_sn"], "model": maint_device_ready["model"],
                                               "total_usage_hours": maint_device_ready["total_usage_hours"], "status": "ready", "status_label": "✅ พร้อมใช้งาน"},
                                          ],
                                          "Resin": [], "Wash & Cure": [], "Other": [],
                                      },
                                      my_location={"name": customer["name"], "latitude": 13.75, "longitude": 100.52},
                                      centers_with_geo=[center, center2]),
    "device_print_checklist.html": dict(BASE, user=user_customer, device=maint_device,
                                          checklist=[checklist_item1, checklist_item2], error=None),
    "device_maintenance_log.html": dict(BASE, user=user_customer, device=maint_device,
                                          plan_items=[plan_item_days, plan_item_hours], error=None,
                                          today="2026-07-25", interval_labels=MAINTENANCE_INTERVAL_TYPE_LABELS),
    "device_history.html": dict(BASE, user=user_customer, device=maint_device, overview=overview_maintenance_due,
                                  maint_logs=[maint_log1, maint_log2], print_sessions=[print_session1, print_session2]),
    "notifications.html": dict(BASE, user=user_customer, notifications=[notif_unread, notif_read]),
    "admin_maintenance_plans.html": dict(BASE, user=user_admin, plans=[plan_item_days, plan_item_hours, plan_item_inactive],
                                           device_types=DEVICE_TYPES, interval_labels=MAINTENANCE_INTERVAL_TYPE_LABELS),
    "admin_checklist_items.html": dict(BASE, user=user_admin, items=[checklist_item1, checklist_item2, checklist_item_inactive],
                                         device_types=DEVICE_TYPES),
    "admin_inventory.html": dict(BASE, user=user_admin, parts=[part, part2, part_printer], centers=[center, center2],
                                   error=None, q="", threshold=2000, max_image_mb=5, max_images=9,
                                   categories=PRODUCT_CATEGORIES, category_labels=PRODUCT_CATEGORY_LABELS,
                                   category_icons=PRODUCT_CATEGORY_ICONS,
                                   parts_for_js=[
                                       {"sku": p["part_sku"], "name": p["part_name"], "category": p["category"],
                                        "category_label": PRODUCT_CATEGORY_LABELS.get(p["category"], p["category"]),
                                        "category_icon": PRODUCT_CATEGORY_ICONS.get(p["category"], "📦"),
                                        "description": p["description"] or "", "compatible_models": p.get("compatible_models") or "",
                                        "stock_quantity": p["stock_quantity"], "reorder_level": p["reorder_level"],
                                        "cost_price": p["cost_price"], "labor_fee": p["labor_fee"], "commission_fee": p["commission_fee"],
                                        "center_name": center["name"] if p["center_id"] == center["center_id"] else None,
                                        "images": p["images"], "ownership": p.get("ownership", "owned")}
                                       for p in [part, part2, part_printer]
                                   ]),
    "admin_users.html": dict(BASE, user=user_admin, users=[user_admin, user_manager, user_sales, user_tech, user_customer], centers=[center, center2]),
    "admin_reports.html": dict(BASE, user=user_admin, csat_avg=4.6, csat_count=12, top_issues=[{"issue_category": "หัวพิมพ์อุดตัน", "cnt": 5}],
                                 total_tickets=12, total_closed=8,
                                 total_labor=2000.0, total_parts_cost=1200.0, total_sales_revenue=4500.0, total_sales_commission=300.0,
                                 center_chart_labels=[center["name"], center2["name"]], center_chart_values=[3000, 1500],
                                 center_sales_rows=[{"name": center["name"], "revenue": 3000}, {"name": center2["name"], "revenue": 1500}],
                                 tech_rows=[{"user_id": 2, "name": "ช่างเอก", "assigned_count": 5, "closed_count": 3, "labor_total": 800.0}],
                                 center_rows=[{"name": center["name"], "total_tickets": 8, "closed_tickets": 5}],
                                 part_rows=[{"part_sku": "NZ-04", "part_name": "หัวฉีด 0.4mm", "total_qty": 3, "total_cost": 450.0}],
                                 sales_rows=[{"name": "เซลล์ น้องฟ้า", "order_count": 2, "revenue": 1500.0, "commission": 20.0}],
                                 all_centers=[center, center2], selected_center_id=None, is_manager=False,
                                 centers_for_js=[{"id": center["center_id"], "name": center["name"]},
                                                  {"id": center2["center_id"], "name": center2["name"]}],
                                 selected_center_name=None,
                                 tech_cases_for_js={2: {
                                     "assigned": [{"ticket_id": 101, "model": "Kobra 2", "status": "In Repair",
                                                   "status_label": STATUS_LABELS["In Repair"], "date": "2026-07-10 10:00:00"}],
                                     "closed": [{"ticket_id": 99, "model": "Kobra 2", "date": "2026-07-05 15:00:00"}],
                                     "labor": [{"ticket_id": 101, "model": "Kobra 2", "action": "เปลี่ยนหัวฉีด",
                                                "fee": 200.0, "date": "2026-07-10 11:00:00"}],
                                 }},
                                 report_summary_for_js={
                                     "tickets": [{"ticket_id": 101, "model": "Kobra 2", "customer_name": customer["name"],
                                                  "status_label": STATUS_LABELS["In Repair"], "date": "2026-07-10 10:00:00"}],
                                     "closed": [{"ticket_id": 99, "model": "Kobra 2", "customer_name": customer["name"],
                                                 "date": "2026-07-05 15:00:00"}],
                                     "labor": [{"ticket_id": 101, "model": "Kobra 2", "tech_name": "ช่างเอก",
                                                "action": "เปลี่ยนหัวฉีด", "fee": 200.0, "date": "2026-07-10 11:00:00"}],
                                     "parts": [{"ticket_id": 101, "model": "Kobra 2", "part_sku": "NZ-04",
                                                "part_name": "หัวฉีด 0.4mm", "qty": 1, "cost": 150.0, "date": "2026-07-10 11:00:00"}],
                                     "sales": [{"order_id": 5, "sold_by": "เซลล์ น้องฟ้า", "part_name": "Kobra 3",
                                                "qty": 1, "revenue": 1500.0, "commission": 20.0, "date": "2026-07-08 09:00:00"}],
                                 },
                                 repair_invoices=[
                                     {"ticket_id": 102, "closed_at": "2026-07-05 15:00:00", "model": "Kobra 2",
                                      "customer_name": customer["name"], "tech_name": "ช่างเอก",
                                      "log_items": [
                                          {"created_at": "2026-07-05 14:00:00", "action": "เปลี่ยนหัวฉีด",
                                           "part_name": "หัวฉีด 0.4mm", "part_cost": 150.0, "is_claim": False,
                                           "labor_fee": 200.0, "line_total": 350.0, "tech_notes": "พบปัญหาที่หัวฉีด"},
                                          {"created_at": "2026-07-05 14:30:00", "action": "เปลี่ยนสายพาน (เคลมประกัน)",
                                           "part_name": "สายพาน X-axis", "part_cost": 0.0, "is_claim": True,
                                           "labor_fee": 100.0, "line_total": 100.0, "tech_notes": None},
                                      ], "total": 450.0, "claim_status": "partial",
                                      "invoice_recorded": True, "invoice_recorded_at": "2026-07-06 09:00:00",
                                      "invoice_recorded_by_name": "แอดมิน สมชาย"},
                                     {"ticket_id": 105, "closed_at": "2026-07-08 10:00:00", "model": "Kobra 3",
                                      "customer_name": customer2["name"], "tech_name": "-",
                                      "log_items": [], "total": 0.0, "claim_status": "none",
                                      "invoice_recorded": False, "invoice_recorded_at": None,
                                      "invoice_recorded_by_name": None},
                                 ]),
    "manager_approvals.html": dict(BASE, user=user_manager, requests=[]),
    "manager_csat.html": dict(BASE, user=user_manager, csat_avg=4.6, csat_count=12, ratings=[{"score": 5, "cnt": 8}]),
    "customer_new_ticket.html": dict(BASE, user=user_customer,
                                       devices=[dict(device, has_open_ticket=False), dict(device, device_sn="AC-KOBRA2-0002", has_open_ticket=True)],
                                       error=None, centers=[center], all_centers=[center, center2],
                                       centers_with_geo=[center, center2], preferred_center_id=center["center_id"],
                                       max_images=5, max_video_mb=20),
    "customer_tickets.html": dict(BASE, user=user_customer, tickets=[ticket, ticket_closed]),
    "customer_ticket_detail.html": dict(BASE, user=user_customer, t=ticket_closed, media=[], logs=[log], quotes=[quote],
                                          invoice_items=invoice_items, invoice_total=350.0, payments=payments),
    "tech_tasks.html": dict(BASE, user=user_tech, tickets=[ticket]),
    "tech_report.html": dict(BASE, user=user_tech, tickets=[ticket, ticket_closed],
                               status_summary=[
                                   {"status": s, "label": STATUS_LABELS[s], "icon": STATUS_ICONS[s],
                                    "count": (1 if s in ("In Repair", "Resolved/Closed") else 0)}
                                   for s in STATUSES
                               ],
                               resolved_count=1, parts_rows=[
                                   {"sku": part["part_sku"], "part_name": part["part_name"], "total_qty": 3, "times_used": 2},
                                   {"sku": "OLD-01", "part_name": None, "total_qty": 1, "times_used": 1},
                               ], total_parts_qty=4, pending_count=1, date_from="2026-07-01", date_to="2026-07-31"),
    "tech_ticket_detail.html": dict(BASE, user=user_tech, t=ticket_closed, media=[], logs=[log, log_claim], parts=[part, part2],
                                      quotes=[quote], invoice_items=invoice_items, invoice_total=350.0, payments=payments,
                                      parts_for_js=[
                                          {"sku": part["part_sku"], "name": part["part_name"], "label": f"{part['part_name']} ({part['part_sku']})",
                                           "stock": part["stock_quantity"], "cost": part["cost_price"], "labor": part["labor_fee"]},
                                          {"sku": part2["part_sku"], "name": part2["part_name"], "label": f"{part2['part_name']} ({part2['part_sku']})",
                                           "stock": part2["stock_quantity"], "cost": part2["cost_price"], "labor": part2["labor_fee"]},
                                      ],
                                      part_name_lookup={part["part_sku"]: part["part_name"], part2["part_sku"]: part2["part_name"]},
                                      maintenance_plan_items=[plan_item_days, plan_item_hours], maintenance_logs=[maint_log1, maint_log2],
                                      interval_labels=MAINTENANCE_INTERVAL_TYPE_LABELS, today="2026-07-27"),
    "tech_quote_form.html": dict(BASE, user=user_tech, t=ticket, parts=[part, part2]),
    "sales_orders.html": dict(BASE, user=user_sales, orders=[sale_order], chart_labels=["2026-06", "2026-07"], chart_values=[1200, 1500],
                                unassigned=False, date_from="2026-07-01", date_to="2026-07-31",
                                category_summary=[
                                    {"category": "FDM_Printer", "label": "เครื่องพิมพ์ FDM", "icon": "🖨️", "color": "#3f7fe0", "revenue": 15000.0, "qty": 1},
                                    {"category": "Resin_Printer", "label": "เครื่องพิมพ์ Resin", "icon": "🧪", "color": "#6c4fd6", "revenue": 0, "qty": 0},
                                    {"category": "Spare_Part", "label": "อะไหล่", "icon": "🔧", "color": "#22c9e6", "revenue": 300.0, "qty": 2},
                                    {"category": "Material", "label": "วัสดุพิมพ์", "icon": "🧵", "color": "#f1c40f", "revenue": 590.0, "qty": 1},
                                    {"category": "Other", "label": "อื่นๆ", "icon": "📦", "color": "#8a94a6", "revenue": 0, "qty": 0},
                                ]),
    "sales_order_detail.html": dict(BASE, user=user_sales, order=sale_order, items=[sale_item], total_amount=1500.0, total_commission=20.0),
    "sales_new.html": dict(BASE, user=user_sales, customers=[customer, customer2], parts=[part, part2],
                             center=center, selling_centers=[center], blocked_reason=None, error=None, parts_for_js=[
        {"sku": part["part_sku"], "name": part["part_name"], "price": part["cost_price"], "stock": part["stock_quantity"], "label": f"{part['part_name']} ({part['part_sku']})"},
        {"sku": part2["part_sku"], "name": part2["part_name"], "price": part2["cost_price"], "stock": part2["stock_quantity"], "label": f"{part2['part_name']} ({part2['part_sku']})"},
    ]),
    "quote_print.html": dict(BASE, t=dict(ticket, customer_name=customer["name"], phone=customer["phone"], address=customer["address"]),
                               q=quote, items=quote["line_items"], total=quote["total"]),
    "invoice_print.html": dict(BASE, t=dict(ticket_closed, customer_name=customer["name"], phone=customer["phone"], address=customer["address"]),
                                 invoice_items=invoice_items, invoice_total=350.0),
    "receipt_print.html": dict(BASE, t=dict(ticket_closed, customer_name=customer["name"], phone=customer["phone"], address=customer["address"]),
                                 invoice_items=invoice_items, invoice_total=350.0, payments=[payment_confirmed], total_paid=350.0),
    "ticket_pay.html": dict(BASE, user=user_customer, t=ticket_closed, invoice_total=350.0, payments=payments,
                              error=None, max_slip_mb=5),
}

# --- TDPrinter Partnership Workflow (Restock Orders + Consignment Settlements) ---
RESTOCK_STATUS_LABELS_TEST = {
    "requested": "🕓 รอ HQ ดำเนินการ",
    "processing": "📦 HQ กำลังเตรียมจัดส่ง",
    "shipped": "🚚 จัดส่งแล้ว (ระหว่างทาง)",
    "received": "✅ ได้รับของแล้ว",
    "cancelled": "❌ ยกเลิก",
}
CONSIGNMENT_STATUS_LABELS_TEST = {
    "draft": "📝 ร่าง (ยังไม่ส่ง)",
    "submitted": "📨 ส่งรายงานแล้ว รอ HQ ตรวจสอบ",
    "reconciled": "🔎 HQ ตรวจสอบแล้ว รอชำระเงิน",
    "paid": "✅ ชำระเงินเรียบร้อย",
}
restock_item1 = {"item_id": 1, "order_id": 1, "part_sku": part2["part_sku"], "part_name": part2["part_name"],
                  "quantity_requested": 10, "quantity_received": None}
restock_item2 = {"item_id": 2, "order_id": 1, "part_sku": part["part_sku"], "part_name": part["part_name"],
                  "quantity_requested": 5, "quantity_received": None}
restock_order_requested = {"order_id": 1, "center_id": 1, "center_name": center["name"], "requested_by": 4,
                            "requested_by_name": user_manager["name"], "status": "requested",
                            "status_label": RESTOCK_STATUS_LABELS_TEST["requested"], "tracking_number": None,
                            "notes": "ต้องการด่วนภายในสัปดาห์นี้", "created_at": "2026-07-20 09:00:00",
                            "processed_at": None, "shipped_at": None, "received_at": None,
                            "order_items": [restock_item1, restock_item2]}
restock_order_shipped = dict(restock_order_requested, order_id=2, status="shipped",
                              status_label=RESTOCK_STATUS_LABELS_TEST["shipped"], tracking_number="TH1234567890",
                              order_items=[dict(restock_item1, item_id=3, order_id=2)])
parts_for_js_restock = [
    {"sku": part["part_sku"], "name": part["part_name"], "price": part["cost_price"],
     "stock": part["stock_quantity"], "label": f"{part['part_name']} ({part['part_sku']})"},
    {"sku": part2["part_sku"], "name": part2["part_name"], "price": part2["cost_price"],
     "stock": part2["stock_quantity"], "label": f"{part2['part_name']} ({part2['part_sku']})"},
]
CONTEXTS["manager_restock_orders.html"] = dict(BASE, user=user_manager, parts=[part, part2],
    parts_for_js=parts_for_js_restock, orders=[restock_order_requested, restock_order_shipped],
    restock_status_labels=RESTOCK_STATUS_LABELS_TEST, error=None)
CONTEXTS["admin_restock_orders.html"] = dict(BASE, user=user_admin,
    orders=[restock_order_requested, restock_order_shipped], restock_status_labels=RESTOCK_STATUS_LABELS_TEST)

settlement_submitted = {"settlement_id": 1, "center_id": 1, "center_name": center["name"], "period_month": "2026-07",
                         "total_consignment_sales": 4500.0, "status": "submitted", "invoice_number": None,
                         "notes": None, "submitted_by": 4, "reconciled_by": None,
                         "submitted_at": "2026-07-31 18:00:00", "reconciled_at": None, "paid_at": None}
settlement_reconciled = dict(settlement_submitted, settlement_id=2, period_month="2026-06", status="reconciled",
                              invoice_number="INV-2026-0042", reconciled_by=1, reconciled_at="2026-07-02 10:00:00")
settlement_draft = dict(settlement_submitted, settlement_id=3, period_month="2026-08", status="draft",
                         submitted_at=None)
CONTEXTS["manager_settlements.html"] = dict(BASE, user=user_manager, period="2026-08",
    current=settlement_draft, current_total=1200.0, history=[settlement_reconciled],
    settlement_status_labels=CONSIGNMENT_STATUS_LABELS_TEST)
CONTEXTS["admin_settlements.html"] = dict(BASE, user=user_admin,
    settlements=[settlement_submitted, settlement_reconciled], settlement_status_labels=CONSIGNMENT_STATUS_LABELS_TEST)

# บริบทเพิ่มเติมสำหรับตรวจสอบ admin_new_ticket.html กรณี manager/sales (ผูกสาขาตัวเองตายตัว, blocked_reason ต่างๆ)
# ด้วยตนเองนอกลูป CONTEXTS หลัก (ไม่ใช่ template filename จริง จึงแยกไว้ต่างหาก)
ADMIN_NEW_TICKET_MANAGER_FIXED_CENTER = dict(BASE, user=user_manager, error=None,
    max_images=10, max_video_mb=10,
    customers=[customer, customer2],
    customers_for_js=[
        {"id": customer["customer_id"], "name": customer["name"], "phone": customer["phone"], "tax_id": customer["tax_id"]},
    ],
    devices_by_customer_for_js={
        customer["customer_id"]: [{"sn": device_full["device_sn"], "model": device_full["model"], "has_open_ticket": True}],
    },
    repair_centers=[center], fixed_center=center, blocked_reason=None)
ADMIN_NEW_TICKET_BLOCKED_UNASSIGNED = dict(BASE, user=user_sales, error=None,
    max_images=10, max_video_mb=10, customers=[], customers_for_js=[], devices_by_customer_for_js={},
    repair_centers=[], fixed_center=None, blocked_reason="unassigned")

GUIDE_SECTIONS_TEST = [
    {"slug": "public", "title": "หน้าเว็บสาธารณะ", "icon": "🌐", "subtitle": "หน้าแรก ดูสินค้า และเช็กสถานะงานซ่อม", "roles": None},
    {"slug": "admin", "title": "แอดมิน", "icon": "🛠️", "subtitle": "จัดการระบบทั้งหมด", "roles": {"admin"}},
    {"slug": "manager_sales", "title": "ผู้จัดการศูนย์ / เซล", "icon": "🏢", "subtitle": "จัดการงานซ่อมและการขาย", "roles": {"admin", "manager", "sales"}},
    {"slug": "technician", "title": "ช่างซ่อม", "icon": "🔧", "subtitle": "รับงาน บันทึกการซ่อม", "roles": {"admin", "technician"}},
    {"slug": "customer", "title": "ลูกค้า", "icon": "🧑‍💻", "subtitle": "แจ้งซ่อม ติดตามสถานะ", "roles": {"admin", "customer"}},
]
CONTEXTS["guide_index.html"] = dict(BASE, user=None,
    sections=[dict(s, allowed=(s["roles"] is None)) for s in GUIDE_SECTIONS_TEST])
CONTEXTS["guide_public.html"] = dict(BASE, user=None, section=GUIDE_SECTIONS_TEST[0])
CONTEXTS["guide_admin.html"] = dict(BASE, user=user_admin, section=GUIDE_SECTIONS_TEST[1])
CONTEXTS["guide_manager_sales.html"] = dict(BASE, user=user_manager, section=GUIDE_SECTIONS_TEST[2])
CONTEXTS["guide_technician.html"] = dict(BASE, user=user_tech, section=GUIDE_SECTIONS_TEST[3])
CONTEXTS["guide_customer.html"] = dict(BASE, user=user_customer, section=GUIDE_SECTIONS_TEST[4])

errors = []
for name in sorted(env.list_templates()):
    if name.startswith("base") or name.startswith("_"):
        continue
    ctx = CONTEXTS.get(name)
    if ctx is None:
        errors.append(f"{name}: NO CONTEXT DEFINED - skipped")
        continue
    try:
        tmpl = env.get_template(name)
        html = tmpl.render(**RENDER_DEFAULTS, **ctx)
    except Exception as e:
        errors.append(f"{name}: RENDER ERROR: {type(e).__name__}: {e}")
        continue
    leftover = re.findall(r"\{\{.*?\}\}|\{%.*?%\}", html)
    if leftover:
        errors.append(f"{name}: UNRENDERED JINJA: {leftover[:5]}")

print(f"Checked {len([n for n in env.list_templates() if not n.startswith('base')])} templates")
if errors:
    print("ISSUES:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
else:
    print("ALL TEMPLATES RENDERED CLEANLY")
