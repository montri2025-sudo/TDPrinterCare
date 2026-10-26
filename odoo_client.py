"""odoo_client.py — ซิงก์ข้อมูลของแอปนี้ไปยัง Odoo ผ่าน XML-RPC

ซิงก์ได้ 4 ประเภท:
  - ลูกค้า (Customers)               -> res.partner   (customer_rank=1)
  - สินค้า/อะไหล่ (Spare_Parts)        -> product.template
  - พนักงาน/ทีมงานภายใน (Users, ไม่รวม role='customer') -> res.users
  - ศูนย์บริการพาร์ทเนอร์ (Service_Centers) -> res.partner (is_company=1, แยกจากลูกค้า)

เป็นโมดูลเสริมที่ "ไม่บังคับใช้งาน" ตามแพทเทิร์นเดียวกับ SMTP/Google/LINE ในไฟล์นี้:
- ถ้าไม่ได้ตั้งค่า ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_API_KEY ไว้ใน environment variables
  ทุกฟังก์ชัน sync_* จะข้ามการทำงานเงียบๆ (return None) ทันที ไม่กระทบการสร้าง/แก้ไขข้อมูลปกติ
- ทุกการเรียก XML-RPC ครอบด้วย try/except กว้างๆ เสมอ — ถ้า Odoo ล่ม/ตั้งค่าผิด/เน็ตหลุด จะแค่ log
  ข้อความไว้ (print ไปที่ stdout ซึ่ง docker logs อ่านได้) แล้ว "ไม่ throw" ออกไป เพื่อไม่ให้การซิงก์ที่ล้มเหลว
  ไปทำให้ request หลักของผู้ใช้ (สร้าง/แก้ไขข้อมูล) ล่มตามไปด้วย
- ใช้ stdlib xmlrpc.client ล้วนๆ ไม่ต้องเพิ่ม dependency ใหม่ใน requirements.txt

กลไกจับคู่ข้อมูลซ้ำ (idempotent matching) — ต่างกันไปตามชนิดข้อมูล เพราะ key ทางธุรกิจต่างกัน:
  - ลูกค้า/ศูนย์บริการ: ใช้ฟิลด์ "ref" ของ res.partner เก็บ "TDSP-CUST-{id}" / "TDSP-CENTER-{id}"
  - สินค้า: ใช้ "default_code" (รหัส SKU) ของ product.template ตรงๆ เพราะ part_sku ไม่ซ้ำกันอยู่แล้วในระบบนี้
  - พนักงาน: ใช้ "login" ของ res.users = username ตรงๆ เพราะ username ไม่ซ้ำกันอยู่แล้วในระบบนี้
  ทุกกรณีถ้ามี odoo_*_id แคชไว้ (คอลัมน์ในตารางแอปนี้) จะลองใช้ก่อนเพื่อลดรอบ round-trip ไป Odoo
  แต่ยัง verify ว่ายังมีอยู่จริงฝั่ง Odoo เสมอ (เผื่อถูกลบไปฝั่งนั้นแล้ว) ก่อน fallback ไป search ด้วย key หลัก

การตั้งค่า timeout: xmlrpc.client.ServerProxy ของ stdlib ไม่มีพารามิเตอร์ timeout ตรงๆ ต้องสร้าง
  Transport ของตัวเองที่ตั้ง socket timeout ให้ (ดูคลาส _TimeoutTransport ด้านล่าง) — ป้องกันไม่ให้
  การเรียก sync_*() แบบ synchronous ระหว่าง request ทำให้ผู้ใช้ต้องรอค้างนานเกินไปถ้า Odoo ไม่ตอบ
"""

import socket
import xmlrpc.client

import db

ODOO_REQUEST_TIMEOUT_SEC = 5  # ไม่ควรตั้งนานเกินไป เพราะการซิงก์นี้รันแบบ synchronous ระหว่าง request ของผู้ใช้จริง


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc.client.Transport ธรรมดาไม่มี timeout ให้ตั้ง ต้อง subclass เพื่อกำหนด socket timeout เอง
    (ป้องกัน request ของผู้ใช้ค้างนานเกินไปถ้าเซิร์ฟเวอร์ Odoo ไม่ตอบสนอง/เน็ตมีปัญหา)"""

    def __init__(self, timeout, use_https=False):
        super().__init__()
        self._timeout = timeout
        self._use_https = use_https

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _make_proxy(path):
    """สร้าง ServerProxy ไปยัง endpoint ของ Odoo (เช่น /xmlrpc/2/common หรือ /xmlrpc/2/object)
    พร้อม timeout ที่ตั้งไว้ — คืนค่า None ถ้ายังไม่ได้ตั้งค่า ODOO_URL"""
    if not db.ODOO_URL:
        return None
    url = f"{db.ODOO_URL}{path}"
    transport = (_TimeoutSafeTransport(ODOO_REQUEST_TIMEOUT_SEC) if url.startswith("https://")
                 else _TimeoutTransport(ODOO_REQUEST_TIMEOUT_SEC))
    return xmlrpc.client.ServerProxy(url, transport=transport, allow_none=True)


def _is_configured():
    return bool(db.ODOO_URL and db.ODOO_DB and db.ODOO_USERNAME and db.ODOO_API_KEY)


def _authenticate():
    """ล็อกอินเข้า Odoo ผ่าน endpoint common แล้วคืนค่า uid (int) — คืน None ถ้าล้มเหลว/ยังไม่ตั้งค่า
    หมายเหตุ: Odoo รองรับใช้ API key แทนรหัสผ่านตรงพารามิเตอร์ password ของ authenticate() ได้เลย
    (ไม่ต้องมี endpoint แยกสำหรับ API key)"""
    if not _is_configured():
        return None
    try:
        common = _make_proxy("/xmlrpc/2/common")
        uid = common.authenticate(db.ODOO_DB, db.ODOO_USERNAME, db.ODOO_API_KEY, {})
        if not uid:
            print("[odoo_client] เข้าสู่ระบบ Odoo ไม่สำเร็จ — ตรวจสอบ ODOO_DB/ODOO_USERNAME/ODOO_API_KEY อีกครั้ง")
            return None
        return uid
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError) as e:
        print(f"[odoo_client] เชื่อมต่อ Odoo ไม่สำเร็จ (authenticate): {e}")
        return None


def _customer_ref(customer_id):
    return f"TDSP-CUST-{customer_id}"


def sync_customer(customer_id, name, phone=None, email=None, address=None, tax_id=None, odoo_partner_id=None):
    """ซิงก์ข้อมูลลูกค้า 1 คนไปยัง Odoo เป็น res.partner — สร้างใหม่ถ้ายังไม่เคยมี หรืออัปเดตถ้ามีอยู่แล้ว
    (จับคู่ผ่านฟิลด์ ref="TDSP-CUST-{customer_id}" หรือ odoo_partner_id ที่แคชไว้ถ้ามี)

    คืนค่า: partner_id (int) ของ Odoo ถ้าสำเร็จ, หรือ None ถ้าข้าม/ล้มเหลว (ไม่ throw exception ออกไป
    เด็ดขาด — เรียกใช้จาก route handler ได้โดยไม่ต้องกลัวว่าจะทำให้การสร้าง/แก้ไขลูกค้าใน DB หลักล่มไปด้วย)

    หมายเหตุ: address ในระบบนี้เป็นช่องข้อความเดียว (ไม่ได้แยก street/city/zip) จึงแมปแบบง่ายไปที่ฟิลด์
    "street" ของ Odoo เท่านั้น — ถ้าต้องการแยกละเอียดกว่านี้ (city/state/zip) ต้องแก้ที่ฟอร์มลูกค้าในแอปก่อน"""
    if not _is_configured():
        return None
    if not name or not name.strip():
        return None

    uid = _authenticate()
    if uid is None:
        return None

    try:
        models = _make_proxy("/xmlrpc/2/object")
        ref = _customer_ref(customer_id)

        partner_id = None
        # ถ้ามี odoo_partner_id แคชไว้แล้ว (จากซิงก์ครั้งก่อน) ลองใช้ก่อนเพื่อลดรอบ round-trip —
        # แต่ยังต้อง verify ว่า partner นั้นยังมีอยู่จริงใน Odoo (เผื่อถูกลบไปฝั่ง Odoo แล้ว)
        if odoo_partner_id:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "res.partner", "search", [[["id", "=", int(odoo_partner_id)]]],
            )
            if found:
                partner_id = int(odoo_partner_id)

        if partner_id is None:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "res.partner", "search", [[["ref", "=", ref]]],
            )
            if found:
                partner_id = found[0]

        values = {
            "name": name.strip(),
            "phone": (phone or "").strip() or False,
            "email": (email or "").strip() or False,
            "street": (address or "").strip() or False,
            "vat": (tax_id or "").strip() or False,
            "ref": ref,
            "customer_rank": 1,  # ทำเครื่องหมายว่าเป็นลูกค้า (แสดงในเมนู Customers ของ Odoo)
        }

        if partner_id:
            models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "res.partner", "write", [[partner_id], values])
        else:
            partner_id = models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "res.partner", "create", [values])

        return partner_id
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError) as e:
        print(f"[odoo_client] ซิงก์ลูกค้า customer_id={customer_id} ไป Odoo ไม่สำเร็จ: {e}")
        return None


def _center_ref(center_id):
    return f"TDSP-CENTER-{center_id}"


# แคชชื่อหมวดหมู่สินค้า -> id ของ product.category ฝั่ง Odoo ไว้ในหน่วยความจำ (key = (ODOO_URL, ODOO_DB, ชื่อหมวดหมู่))
# กันไม่ต้อง search/create ซ้ำทุกครั้งที่ซิงก์สินค้า — ใช้ได้ตราบเท่าที่ process ของแอปยังไม่ restart
# (ถ้ามีคนไปเปลี่ยนชื่อหมวดหมู่ในฝั่ง Odoo เองหลังจากนี้ แคชนี้จะไม่รู้ ต้อง restart แอปเพื่อล้างแคช)
_category_id_cache = {}


def _get_or_create_category(models, uid, category_label):
    """หา id ของ product.category ที่ชื่อตรงกับ category_label (เช่น "อะไหล่", "วัสดุพิมพ์") — ถ้ายังไม่มี
    หมวดหมู่นี้ใน Odoo จะสร้างให้ใหม่อัตโนมัติ (เป็นหมวดหมู่ระดับบนสุด ไม่ผูกกับหมวดหมู่แม่ใดๆ) แล้วแคชผลไว้
    เพื่อไม่ต้อง round-trip ซ้ำในการซิงก์ครั้งถัดๆ ไป — คืน None ถ้าไม่มี category_label หรือเกิดข้อผิดพลาด"""
    if not category_label:
        return None
    cache_key = (db.ODOO_URL, db.ODOO_DB, category_label)
    if cache_key in _category_id_cache:
        return _category_id_cache[cache_key]
    try:
        found = models.execute_kw(
            db.ODOO_DB, uid, db.ODOO_API_KEY,
            "product.category", "search", [[["name", "=", category_label]]],
        )
        if found:
            categ_id = found[0]
        else:
            categ_id = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "product.category", "create", [{"name": category_label}],
            )
        _category_id_cache[cache_key] = categ_id
        return categ_id
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError) as e:
        print(f"[odoo_client] หา/สร้างหมวดหมู่สินค้า '{category_label}' ใน Odoo ไม่สำเร็จ: {e}")
        return None


def sync_product(sku, name, price=None, description=None, category_label=None, odoo_product_id=None,
                  image_b64=None):
    """ซิงก์สินค้า/อะไหล่ 1 รายการไปยัง Odoo เป็น product.template — จับคู่ผ่าน default_code=SKU
    (part_sku ในระบบนี้เป็น primary key อยู่แล้ว ไม่ซ้ำกัน จึงใช้เป็น key หลักได้ตรงๆ ไม่ต้องมี prefix)

    ถ้าระบุ category_label (เช่น "อะไหล่", "เครื่องพิมพ์ FDM") จะหา/สร้างหมวดหมู่สินค้า (product.category)
    ที่ชื่อตรงกันใน Odoo ให้อัตโนมัติ แล้วตั้งเป็น categ_id ของสินค้านี้ — ทำให้ประเภทสินค้าในระบบนี้ (FDM/Resin/
    อะไหล่/วัสดุพิมพ์/อื่นๆ) กลายเป็นหมวดหมู่สินค้าจริงใน Odoo ด้วย ไม่ต้องไปสร้างเองทีละหมวดในฝั่ง Odoo

    ถ้าระบุ image_b64 (รูปปกหลักของสินค้า เข้ารหัส base64 เป็น str แล้ว) จะตั้งเป็น image_1920 ของสินค้านี้
    ด้วย — เป็นรูปเดียว (รูปปก) เท่านั้น ไม่รองรับรูปแกลเลอรีเพิ่มเติมผ่าน API นี้ (ต้องไปแนบเองในฝั่ง Odoo
    ถ้าต้องการรูปเพิ่มเติม) ค่าไม่ระบุ/None จะไม่แตะต้อง/ไม่เขียนทับรูปที่มีอยู่แล้วใน Odoo

    หมายเหตุ: ระบบนี้มีราคาสินค้าแค่ช่องเดียว (cost_price) ไม่ได้แยกราคาทุน/ราคาขาย จึงแมป price
    เดียวกันไปทั้ง standard_price (ราคาทุนใน Odoo) และ list_price (ราคาขายใน Odoo) — ถ้าต้องการแยก
    ราคาขายที่ต่างจากราคาทุนใน Odoo ภายหลัง ต้องไปปรับที่ Odoo เองหลังซิงก์ครั้งแรก (ซิงก์ครั้งถัดไป
    จะเขียนทับราคาขายกลับไปเท่าราคาทุนเสมอ เว้นแต่จะแก้ระบบนี้ให้มีช่องราคาขายแยกต่างหากก่อน)"""
    if not _is_configured():
        return None
    if not name or not name.strip() or not sku:
        return None

    uid = _authenticate()
    if uid is None:
        return None

    try:
        models = _make_proxy("/xmlrpc/2/object")

        product_id = None
        if odoo_product_id:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "product.template", "search", [[["id", "=", int(odoo_product_id)]]],
            )
            if found:
                product_id = int(odoo_product_id)

        if product_id is None:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "product.template", "search", [[["default_code", "=", sku]]],
            )
            if found:
                product_id = found[0]

        values = {
            "name": name.strip(),
            "default_code": sku,
            "description_sale": (description or "").strip() or False,
        }
        if price is not None:
            values["list_price"] = float(price)
            values["standard_price"] = float(price)
        if category_label:
            categ_id = _get_or_create_category(models, uid, category_label)
            if categ_id:
                values["categ_id"] = categ_id
        if image_b64:
            values["image_1920"] = image_b64

        if product_id:
            models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "product.template", "write", [[product_id], values])
        else:
            product_id = models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "product.template", "create", [values])

        return product_id
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError) as e:
        print(f"[odoo_client] ซิงก์สินค้า sku={sku} ไป Odoo ไม่สำเร็จ: {e}")
        return None


def _internal_user_group_id(models, uid):
    """หา id ของกลุ่มสิทธิ์ 'Internal User' (base.group_user) ใน Odoo — ใช้เป็นสิทธิ์เริ่มต้นขั้นต่ำ
    สำหรับพนักงานที่ซิงก์เข้าไปใหม่ (ให้เข้า Odoo ได้แต่ไม่มีสิทธิ์พิเศษอะไร) แอดมิน Odoo ต้องไปปรับ
    สิทธิ์เพิ่มเติมเองภายหลังตามหน้าที่จริงของแต่ละคน (Settings -> Users) — คืน None ถ้าหาไม่เจอ
    (สร้าง user แบบไม่มีกลุ่มระบุแทน ซึ่ง Odoo อาจให้สิทธิ์ portal/ไม่มีสิทธิ์เข้า backend เลย)"""
    try:
        data = models.execute_kw(
            db.ODOO_DB, uid, db.ODOO_API_KEY,
            "ir.model.data", "search_read",
            [[["module", "=", "base"], ["name", "=", "group_user"]]],
            {"fields": ["res_id"]},
        )
        if data:
            return data[0]["res_id"]
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError):
        pass
    return None


def sync_staff_user(user_id, username, name, phone=None, odoo_user_id=None):
    """ซิงก์บัญชีพนักงาน/ทีมงานภายใน (แอดมิน/ผู้จัดการ/เซล/ช่าง — ไม่ใช่ role='customer') ไปยัง Odoo
    เป็น res.users — จับคู่ผ่าน login=username ตรงๆ (username ในระบบนี้ไม่ซ้ำกันอยู่แล้ว)

    หมายเหตุสำคัญ: ระบบนี้ไม่มีช่องอีเมลของพนักงาน (มีแค่ username/phone) จึงตั้ง login=username และเว้น
    email ว่างไว้ — ผู้ใช้ที่สร้างใหม่ใน Odoo จะยังไม่มีรหัสผ่าน (ต้องให้แอดมิน Odoo กด "Send Invitation
    Email" หรือตั้งรหัสผ่านให้เองที่ Settings -> Users ภายหลัง เพราะ API ไม่ส่งอีเมลเชิญให้อัตโนมัติ)
    สิทธิ์เริ่มต้นที่ให้คือ "Internal User" (เข้า Odoo ได้แต่ไม่มีสิทธิ์พิเศษ) เท่านั้น — แอดมิน Odoo
    ต้องไปตั้งสิทธิ์เพิ่มเติมเองตามหน้าที่จริงของแต่ละคน"""
    if not _is_configured():
        return None
    if not username or not name or not name.strip():
        return None

    uid = _authenticate()
    if uid is None:
        return None

    try:
        models = _make_proxy("/xmlrpc/2/object")

        res_user_id = None
        if odoo_user_id:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "res.users", "search", [[["id", "=", int(odoo_user_id)]]],
            )
            if found:
                res_user_id = int(odoo_user_id)

        if res_user_id is None:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "res.users", "search", [[["login", "=", username]]],
            )
            if found:
                res_user_id = found[0]

        values = {
            "name": name.strip(),
            "login": username,
            "phone": (phone or "").strip() or False,
        }

        if res_user_id:
            models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "res.users", "write", [[res_user_id], values])
        else:
            group_id = _internal_user_group_id(models, uid)
            if group_id:
                values["groups_id"] = [(6, 0, [group_id])]
            res_user_id = models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "res.users", "create", [values])

        return res_user_id
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError) as e:
        print(f"[odoo_client] ซิงก์พนักงาน user_id={user_id} (username={username}) ไป Odoo ไม่สำเร็จ: {e}")
        return None


def sync_service_center(center_id, name, address=None, phone=None, tax_id=None, email=None, website=None,
                         odoo_partner_id=None):
    """ซิงก์ศูนย์บริการพาร์ทเนอร์ 1 สาขาไปยัง Odoo เป็น res.partner (is_company=1) — จับคู่ผ่านฟิลด์
    ref="TDSP-CENTER-{center_id}" แยกจากลูกค้า (res.partner ของลูกค้าใช้ ref="TDSP-CUST-{id}") จึงไม่ชนกัน
    แม้ id จะซ้ำกันได้ (customer_id กับ center_id เป็นคนละ sequence กัน)"""
    if not _is_configured():
        return None
    if not name or not name.strip():
        return None

    uid = _authenticate()
    if uid is None:
        return None

    try:
        models = _make_proxy("/xmlrpc/2/object")
        ref = _center_ref(center_id)

        partner_id = None
        if odoo_partner_id:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "res.partner", "search", [[["id", "=", int(odoo_partner_id)]]],
            )
            if found:
                partner_id = int(odoo_partner_id)

        if partner_id is None:
            found = models.execute_kw(
                db.ODOO_DB, uid, db.ODOO_API_KEY,
                "res.partner", "search", [[["ref", "=", ref]]],
            )
            if found:
                partner_id = found[0]

        values = {
            "name": name.strip(),
            "is_company": True,
            "phone": (phone or "").strip() or False,
            "email": (email or "").strip() or False,
            "website": (website or "").strip() or False,
            "street": (address or "").strip() or False,
            "vat": (tax_id or "").strip() or False,
            "ref": ref,
            "supplier_rank": 1,  # ทำเครื่องหมายว่าเป็นคู่ค้า/ซัพพลายเออร์ (แสดงในเมนู Vendors ของ Odoo)
        }

        if partner_id:
            models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "res.partner", "write", [[partner_id], values])
        else:
            partner_id = models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, "res.partner", "create", [values])

        return partner_id
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError) as e:
        print(f"[odoo_client] ซิงก์ศูนย์บริการ center_id={center_id} ไป Odoo ไม่สำเร็จ: {e}")
        return None


class OdooQuotationError(Exception):
    """A safe, user-facing reason that no quotation was synchronized."""


def sync_quotation(source_kind, source_id, partner_id, lines, notes=""):
    """Create one draft per source reference. Existing Odoo documents are never overwritten.

    Caller serializes requests by locking the source order row. This only creates
    a quotation; no confirm, invoice, delivery, email or payment action is called.
    Prices are THB and taxes are left empty for explicit review in Odoo.
    """
    import hashlib
    import html
    import json
    import math
    if source_kind not in ("sale", "restock") or not isinstance(source_id, int) or source_id <= 0:
        raise OdooQuotationError("ประเภทหรือหมายเลขเอกสารไม่ถูกต้อง")
    if not partner_id or not lines:
        raise OdooQuotationError("ต้องมีลูกค้าและรายการสินค้าอย่างน้อยหนึ่งรายการ")
    for line in lines:
        if (not line.get("template_id") or not math.isfinite(float(line["quantity"]))
                or float(line["quantity"]) <= 0 or not math.isfinite(float(line["unit_price"]))
                or float(line["unit_price"]) < 0):
            raise OdooQuotationError("จำนวนหรือราคาสินค้าไม่ถูกต้อง")
    if not _is_configured():
        raise OdooQuotationError("ยังไม่ได้ตั้งค่าการเชื่อมต่อ Odoo")
    uid = _authenticate()
    if not uid:
        raise OdooQuotationError("เชื่อมต่อหรือเข้าสู่ระบบ Odoo ไม่สำเร็จ")
    models = _make_proxy("/xmlrpc/2/object")
    def call(model, method, args, kwargs=None):
        return models.execute_kw(db.ODOO_DB, uid, db.ODOO_API_KEY, model, method, args, kwargs or {})
    ref = f"TDSP-{source_kind.upper()}-{source_id}"
    canonical = json.dumps({"partner":partner_id,"lines":lines,"notes":notes}, sort_keys=True, ensure_ascii=False)
    digest = "TDSP-SOURCE-SHA256:" + hashlib.sha256(canonical.encode()).hexdigest()
    try:
        company_id = call("res.users", "read", [[uid]], {"fields":["company_id"]})[0]["company_id"][0]
        existing = call("sale.order", "search_read", [[["client_order_ref","=",ref],["company_id","=",company_id]]],
                        {"fields":["name","state","note"],"limit":2})
        if len(existing) > 1:
            raise OdooQuotationError("พบเอกสารอ้างอิงซ้ำใน Odoo กรุณาให้ผู้ดูแลตรวจสอบก่อน")
        if existing:
            order = existing[0]
            return {"id":order["id"],"name":order["name"],"state":order["state"],"reference":ref,
                    "reused":True,"source_changed":digest not in (order.get("note") or "")}
        partner = call("res.partner", "read", [[int(partner_id)]], {"fields":["property_product_pricelist"]})
        if not partner or not partner[0].get("property_product_pricelist"):
            raise OdooQuotationError("กรุณาตั้งรายการราคาสกุลเงินบาทให้ลูกค้าใน Odoo ก่อน")
        pricelist_id = partner[0]["property_product_pricelist"][0]
        pricelist = call("product.pricelist", "read", [[pricelist_id]], {"fields":["currency_id"]})[0]
        currency = call("res.currency", "read", [[pricelist["currency_id"][0]]], {"fields":["name"]})[0]
        if currency["name"] != "THB":
            raise OdooQuotationError("รายการราคาลูกค้าใน Odoo ต้องเป็นสกุล THB ก่อนส่งราคาบาท")
        fields = call("sale.order.line", "fields_get", [], {"attributes":["type"]})
        tax_field = "tax_ids" if "tax_ids" in fields else "tax_id"
        commands = []
        for line in lines:
            variants = call("product.product", "search", [[["product_tmpl_id","=",int(line["template_id"])]]], {"limit":2})
            if len(variants) != 1:
                raise OdooQuotationError("สินค้ามีหลายตัวเลือกหรือไม่พบสินค้าใน Odoo ต้องระบุตัวเลือกให้ชัดเจนก่อน")
            commands.append((0,0,{"product_id":variants[0],"name":line["name"],
                "product_uom_qty":float(line["quantity"]),"price_unit":float(line["unit_price"]),
                tax_field:[(5,0,0)]}))
        order_id = call("sale.order", "create", [{"partner_id":int(partner_id),"company_id":company_id,
            "client_order_ref":ref,"origin":ref,"pricelist_id":pricelist_id,"order_line":commands,
            "note":"<p>"+html.escape(digest)+"</p><p>"+html.escape(notes or "")+"</p><p>นำเข้าจาก TDPrinterCare — ตรวจภาษีใน Odoo ก่อนยืนยันเอกสาร</p>"}], {"context":{"mail_create_nosubscribe":True,"tracking_disable":True}})
        order = call("sale.order", "read", [[order_id]], {"fields":["name","state"]})[0]
        if order["state"] != "draft":
            raise OdooQuotationError("Odoo คืนสถานะเอกสารที่ไม่ใช่ใบเสนอราคาร่าง กรุณาตรวจสอบใน Odoo")
        return {"id":order_id,"name":order["name"],"state":order["state"],"reference":ref,
                "reused":False,"source_changed":False}
    except OdooQuotationError:
        raise
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, socket.timeout, OSError, ValueError, KeyError, IndexError, TypeError):
        raise OdooQuotationError("ซิงก์ใบเสนอราคาไม่สำเร็จ กรุณาตรวจการเชื่อมต่อ สิทธิ์ และโมดูล Sales ใน Odoo") from None


def resolve_quotation_product(sku, name):
    """Resolve by exact SKU, creating only missing masters. Never rewrite catalog prices."""
    uid = _authenticate()
    if not uid:
        return None
    try:
        models = _make_proxy('/xmlrpc/2/object')
        found = models.execute_kw(db.ODOO_DB,uid,db.ODOO_API_KEY,'product.template','search',
                                 [[["default_code","=",sku]]],{'limit':2})
        if len(found) > 1:
            return None
        if found:
            return found[0]
        return models.execute_kw(db.ODOO_DB,uid,db.ODOO_API_KEY,'product.template','create',
                                 [{'name':name,'default_code':sku,'sale_ok':True}])
    except (xmlrpc.client.Fault,xmlrpc.client.ProtocolError,socket.timeout,OSError,ValueError):
        return None
