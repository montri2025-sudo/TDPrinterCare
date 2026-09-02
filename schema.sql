-- ระบบบริหารจัดการงานซ่อม (Repair Ticketing System) — PostgreSQL schema
-- หมายเหตุ: ลำดับตารางถูกจัดใหม่ให้ FOREIGN KEY อ้างอิงตารางที่ถูกสร้างไปแล้วเสมอ
-- (เหมือนเดิมกับตอนใช้ MySQL — ต้องมีตารางปลายทางอยู่ก่อน)
--
-- หมายเหตุการแปลงจาก MySQL → PostgreSQL (คงพฤติกรรมเดิมของแอปทุกจุด):
--   * AUTO_INCREMENT PRIMARY KEY → SERIAL PRIMARY KEY
--   * ENUM(...) → VARCHAR(n) + CHECK constraint (ตั้งชื่อ chk_<table>_<column> เพื่อให้ db.py
--     สั่ง DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT ซ้ำได้ทุกครั้งที่แอปสตาร์ท โดยไม่ต้อง track
--     migration ทีละคอลัมน์แบบที่ MySQL เคยทำ)
--   * TINYINT / TINYINT(1) → SMALLINT (ไม่ใช้ BOOLEAN ของ Postgres เพราะโค้ดใน app.py มีการเทียบ/คำนวณ
--     ค่าดิบแบบ SQL literal อยู่หลายจุด เช่น is_active=1, is_active = 1 - is_active, sells_products=1
--     ซึ่ง Postgres BOOLEAN ไม่รองรับการแปลง int→bool โดยปริยายและไม่รองรับเลขคณิต)
--   * DOUBLE → DOUBLE PRECISION
--   * ตัด ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ออกทั้งหมด (Postgres ไม่ต้องระบุ)
--   * UNIQUE KEY name (cols) → CONSTRAINT name UNIQUE (cols)

CREATE TABLE IF NOT EXISTS Service_Centers (
    center_id      SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    address        TEXT,
    phone          TEXT,
    latitude       DOUBLE PRECISION,   -- พิกัดสำหรับปักหมุดบนแผนที่ (ไม่บังคับ)
    longitude      DOUBLE PRECISION,
    supports_fdm   SMALLINT NOT NULL DEFAULT 1,  -- รับซ่อมเครื่องพิมพ์ประเภท FDM
    supports_resin SMALLINT NOT NULL DEFAULT 1,  -- รับซ่อมเครื่องพิมพ์ประเภท Resin
    sells_products SMALLINT NOT NULL DEFAULT 0,  -- สาขานี้จำหน่ายสินค้า (ขายหน้าร้าน) ได้ด้วยหรือไม่
    tax_id              VARCHAR(20),  -- เลขประจำตัวผู้เสียภาษีของสาขา (13 หลัก) — ไม่บังคับกรอก
    logo_filename       TEXT,         -- โลโก้สาขา (รูปภาพเท่านั้น) — แสดงบนหน้าแรกสาธารณะด้วย
    cert_doc_filename   TEXT,         -- หนังสือรับรองบริษัท (รูปภาพ/PDF) — เอกสารภายใน แอดมินเท่านั้นที่เห็น
    por_por_20_filename TEXT,         -- ภ.พ.20 ใบทะเบียนภาษีมูลค่าเพิ่ม (รูปภาพ/PDF) — เอกสารภายใน แอดมินเท่านั้นที่เห็น
    is_headquarters     INTEGER NOT NULL DEFAULT 0,  -- 1 = สาขานี้เป็น "สำนักงานใหญ่" มีได้สาขาเดียวในระบบ
                                                       -- ใช้เป็นข้อมูล "ผู้ส่ง" บนใบส่งสินค้า (delivery note) อัตโนมัติ
    email               VARCHAR(255),  -- อีเมลติดต่อของสาขา (ไม่บังคับ) — แสดงบนใบส่งสินค้าถ้าสาขานี้เป็นสำนักงานใหญ่
    website             VARCHAR(255),  -- เว็บไซต์ของสาขา (ไม่บังคับ) — แสดงบนใบส่งสินค้าถ้าสาขานี้เป็นสำนักงานใหญ่
    odoo_partner_id     INT,  -- id ของ res.partner (is_company=1) ฝั่ง Odoo หลังซิงก์สำเร็จ (NULL = ยังไม่เคยซิงก์)
    bank_name           VARCHAR(100),  -- ชื่อธนาคารสำหรับรับชำระเงิน (เช่น "SCB") — แสดงบนใบเสนอราคา ไม่บังคับกรอก
    bank_account_number VARCHAR(30)    -- เลขบัญชีธนาคารสำหรับรับชำระเงิน — แสดงบนใบเสนอราคา ไม่บังคับกรอก
);

CREATE TABLE IF NOT EXISTS Customers (
    customer_id  SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT,
    email        TEXT,
    line_id      TEXT,
    address      TEXT,
    tax_id       VARCHAR(20),  -- เลขประจำตัวผู้เสียภาษี (13 หลัก) ใช้ออกใบกำกับภาษี — ไม่บังคับกรอก
    latitude     DOUBLE PRECISION,   -- พิกัดที่อยู่ลูกค้า (ไม่บังคับ) — ใช้ปักหมุดบนแผนที่ Dashboard ภายใน (แอดมิน/ผู้จัดการเท่านั้น)
    longitude    DOUBLE PRECISION,
    device_quota INT NOT NULL DEFAULT 3,  -- จำนวนเครื่องพิมพ์สูงสุดที่ลูกค้าลงทะเบียนเองได้ (ตอนสมัคร/หน้า self-service) — แอดมินปรับเพิ่มได้ต่อลูกค้า
    odoo_partner_id INT  -- id ของ res.partner ฝั่ง Odoo หลังซิงก์สำเร็จ (NULL = ยังไม่เคยซิงก์/ไม่ได้ตั้งค่า Odoo) ใช้จับคู่ตอนอัปเดตซ้ำ
);

CREATE TABLE IF NOT EXISTS Users (
    user_id      SERIAL PRIMARY KEY,
    username     VARCHAR(64) UNIQUE NOT NULL,
    password     VARCHAR(255) NOT NULL,             -- PBKDF2-HMAC-SHA256 hash + salt (ดู db.hash_password)
    role         VARCHAR(20) NOT NULL,               -- 'customer','admin','technician','manager','sales'
    name         TEXT NOT NULL,
    phone        VARCHAR(32),                        -- เบอร์โทรติดต่อของพนักงาน (แสดงบนหน้าแรกสาธารณะสำหรับผู้จัดการ/เซล) / เบอร์มือถือลูกค้าที่สมัครผ่าน Google/LINE
    customer_id  INT,                                -- only set when role = 'customer'
    center_id    INT,                                -- ศูนย์บริการที่ผู้ใช้งานสังกัด (สำหรับ staff)
    is_active    SMALLINT NOT NULL DEFAULT 1,         -- 0 = ระงับการใช้งาน (soft delete)
    auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',  -- 'local','google','line' — วิธีสมัคร/ล็อกอิน
    oauth_sub     VARCHAR(255),                       -- รหัสผู้ใช้ที่ Google/LINE ออกให้ (sub/userId) — ใช้จับคู่บัญชีตอนล็อกอินซ้ำ
    odoo_user_id  INT,                                -- id ของ res.users ฝั่ง Odoo หลังซิงก์สำเร็จ (เฉพาะ role staff, NULL = ยังไม่เคยซิงก์)
    created_at    TEXT,                                -- วันที่สร้างบัญชีผู้ใช้งาน (บัญชีเก่าก่อนมีคอลัมน์นี้จะเป็น NULL)
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    CONSTRAINT uniq_oauth_account UNIQUE (auth_provider, oauth_sub),  -- กันสมัครซ้ำบัญชี Google/LINE เดียวกัน (NULL หลายแถวได้ปกติสำหรับบัญชี local)
    CONSTRAINT chk_users_role CHECK (role IN ('customer','admin','technician','manager','sales')),
    CONSTRAINT chk_users_auth_provider CHECK (auth_provider IN ('local','google','line'))
);

CREATE TABLE IF NOT EXISTS Devices (
    device_sn         VARCHAR(64) PRIMARY KEY,
    customer_id       INT NOT NULL,
    model             TEXT NOT NULL,
    type              VARCHAR(20),   -- 'FDM','Resin','Wash & Cure','Other'
    purchase_date     TEXT,
    warranty_end_date TEXT,
    status            VARCHAR(20) NOT NULL DEFAULT 'Active',  -- 'Active','Decommissioned','Sold' — เครื่องที่ไม่ Active จะไม่ขึ้นในรายการแจ้งซ่อมใหม่/แจ้งเตือนบำรุงรักษาอีก
    created_at        TEXT,  -- วันที่ลงทะเบียนเครื่องในระบบ ใช้เรียงเครื่องที่เพิ่มล่าสุดขึ้นก่อนในตารางเครื่องพิมพ์ (เครื่องเก่าก่อนมีคอลัมน์นี้จะเป็น NULL)
    total_usage_hours DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ชั่วโมงการทำงานสะสม — ลูกค้า/ช่างกรอกเองตอนเริ่มงานพิมพ์แต่ละครั้ง (ไม่มีการเชื่อมต่อฮาร์ดแวร์) ใช้คำนวณรอบบำรุงรักษาแบบชั่วโมง
    purchase_proof_filename TEXT,  -- ชื่อไฟล์หลักฐานการสั่งซื้อ (รูปภาพ/PDF) ที่ลูกค้าแนบตอนลงทะเบียนเครื่องเอง — เก็บจริงใน uploads/device_proof/<sn>/
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id),
    CONSTRAINT chk_devices_type CHECK (type IS NULL OR type IN ('FDM','Resin','Wash & Cure','Other')),
    CONSTRAINT chk_devices_status CHECK (status IN ('Active','Decommissioned','Sold'))
);

-- ---------------------------------------------------------- บำรุงรักษา --
-- แผนบำรุงรักษา (Maintenance Scheduler) — งานบำรุงรักษาที่ต้องทำเป็นระยะ กำหนดโดยแอดมิน
-- ผูกกับประเภทเครื่อง (NULL = ใช้กับทุกประเภท) รอบคำนวณได้ 2 แบบ: ตามวัน (สัปดาห์/เดือน) หรือตามชั่วโมงใช้งานสะสม
CREATE TABLE IF NOT EXISTS Maintenance_Plan_Items (
    plan_item_id   SERIAL PRIMARY KEY,
    device_type    VARCHAR(20),  -- NULL = ใช้กับเครื่องพิมพ์ทุกประเภท — 'FDM','Resin','Wash & Cure','Other'
    task_name      TEXT NOT NULL,        -- เช่น "ทาจาระบีแกน X/Y/Z", "เปลี่ยนหัวฉีด"
    interval_type  VARCHAR(10) NOT NULL DEFAULT 'days',  -- 'days','hours'
    interval_value INT NOT NULL,         -- จำนวนวัน (เช่น 7, 30) หรือชั่วโมง (เช่น 50, 200, 500) ตาม interval_type
    is_active      SMALLINT NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    CONSTRAINT chk_maintenance_plan_items_device_type CHECK (device_type IS NULL OR device_type IN ('FDM','Resin','Wash & Cure','Other')),
    CONSTRAINT chk_maintenance_plan_items_interval_type CHECK (interval_type IN ('days','hours'))
);

-- รายการตรวจสอบก่อนพิมพ์ทุกครั้ง (Checklist) — บังคับติ๊กครบทุกข้อก่อนเริ่มงานพิมพ์ได้ (ดู Print_Sessions)
CREATE TABLE IF NOT EXISTS Checklist_Items (
    checklist_item_id SERIAL PRIMARY KEY,
    device_type       VARCHAR(20),  -- NULL = ใช้กับเครื่องพิมพ์ทุกประเภท
    label             TEXT NOT NULL,      -- เช่น "ทำความสะอาดฐานพิมพ์ (Bed)"
    sort_order        INT NOT NULL DEFAULT 0,
    is_active         SMALLINT NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    CONSTRAINT chk_checklist_items_device_type CHECK (device_type IS NULL OR device_type IN ('FDM','Resin','Wash & Cure','Other'))
);

-- บันทึก "เริ่มงานพิมพ์" แต่ละครั้ง — ต้องติ๊ก Checklist ครบก่อนจึงจะบันทึกได้ (บังคับ "ก่อนพิมพ์ทุกครั้ง")
-- ชั่วโมงที่ประเมิน (estimated_hours) จะถูกบวกสะสมเข้า Devices.total_usage_hours ทันทีที่บันทึก
CREATE TABLE IF NOT EXISTS Print_Sessions (
    session_id         SERIAL PRIMARY KEY,
    device_sn          VARCHAR(64) NOT NULL,
    started_by         INT,                 -- Users.user_id ของผู้เริ่มงาน (ลูกค้าเจ้าของเครื่อง หรือช่าง/staff)
    checklist_snapshot TEXT,                -- JSON list ของรายการ Checklist ที่ติ๊กไว้ ณ ตอนนั้น (เก็บสำเนาไว้ แม้ Checklist_Items จะถูกแก้ไขภายหลัง)
    estimated_hours    DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ชั่วโมงที่ประเมินว่าจะใช้พิมพ์งานนี้ (ลูกค้า/ช่างกรอกเอง)
    job_note           TEXT,                -- รายละเอียดงานพิมพ์ (ไม่บังคับ)
    created_at         TEXT NOT NULL,
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (started_by) REFERENCES Users(user_id)
);

-- ประวัติการเข้าบำรุงรักษาเครื่องพิมพ์ตามรอบ (นอกเหนือจากการแจ้งซ่อมปกติ) — ลูกค้าเองก็บันทึกได้ (self-service)
-- ไม่ใช่แค่ staff เท่านั้น — plan_item_id ผูกกับงานบำรุงรักษาตามแผน (NULL = บันทึกอิสระแบบเดิม)
CREATE TABLE IF NOT EXISTS Maintenance_Logs (
    maintenance_id       SERIAL PRIMARY KEY,
    device_sn            VARCHAR(64) NOT NULL,
    plan_item_id         INT,                 -- Maintenance_Plan_Items.plan_item_id ที่ทำ (NULL = บันทึกอิสระ ไม่ผูกแผน)
    performed_at         TEXT NOT NULL,       -- วันที่เข้าบำรุงรักษา (YYYY-MM-DD)
    hours_at_maintenance DOUBLE PRECISION,    -- ชั่วโมงใช้งานสะสมของเครื่อง ณ ตอนบำรุงรักษาครั้งนี้ (snapshot ใช้คำนวณรอบถัดไปแบบชั่วโมง)
    parts_replaced       TEXT,                -- อะไหล่ที่เปลี่ยนไปในการบำรุงรักษาครั้งนี้ (ไม่บังคับ)
    notes                TEXT,
    performed_by         INT,                 -- Users.user_id ของผู้บันทึก (nullable — เผื่อบันทึกย้อนหลัง/ไม่ทราบผู้ทำ, อาจเป็นลูกค้าเองหรือ staff)
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (plan_item_id) REFERENCES Maintenance_Plan_Items(plan_item_id),
    FOREIGN KEY (performed_by) REFERENCES Users(user_id)
);

-- การแจ้งเตือน (Alert & Notification) — สร้างขึ้นทั้งแบบแจ้งในระบบ (in-app) และพยายามส่งอีเมลควบคู่กัน
-- (ถ้าตั้งค่า SMTP_* ไว้) เมื่อเครื่องถึงรอบบำรุงรักษา — ดู _sync_maintenance_notifications() ใน app.py
CREATE TABLE IF NOT EXISTS Notifications (
    notification_id SERIAL PRIMARY KEY,
    user_id          INT NOT NULL,        -- ผู้รับ (เจ้าของเครื่อง หรือ staff ที่เกี่ยวข้อง)
    device_sn        VARCHAR(64),
    plan_item_id     INT,                 -- Maintenance_Plan_Items.plan_item_id ที่แจ้งเตือนนี้เกี่ยวข้อง (ใช้กันแจ้งซ้ำงานเดิม)
    category         VARCHAR(30) NOT NULL DEFAULT 'maintenance_due',  -- 'maintenance_due','general'
    title            TEXT NOT NULL,
    message          TEXT NOT NULL,
    is_read          SMALLINT NOT NULL DEFAULT 0,
    email_sent       SMALLINT NOT NULL DEFAULT 0,
    email_error      TEXT,
    created_at       TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (plan_item_id) REFERENCES Maintenance_Plan_Items(plan_item_id),
    CONSTRAINT chk_notifications_category CHECK (category IN ('maintenance_due','general'))
);

CREATE TABLE IF NOT EXISTS Tickets (
    ticket_id        SERIAL PRIMARY KEY,
    device_sn        VARCHAR(64) NOT NULL,
    issue_category   TEXT,
    description      TEXT,
    center_id        INT,                             -- สาขาที่ลูกค้าเลือกเข้ารับบริการ
    status           VARCHAR(30) NOT NULL DEFAULT 'New',  -- 'New','Diagnosing','Waiting for Parts','In Repair','Testing','Resolved/Closed'
    assigned_tech_id INT,
    created_at       TEXT NOT NULL,
    closed_at        TEXT,
    csat_score       INT,
    csat_comment     TEXT,
    invoice_recorded    SMALLINT NOT NULL DEFAULT 0,  -- ลงบันทึกใบแจ้งหนี้นี้ในบัญชี/ระบบภายนอกแล้วหรือยัง (ติ๊กจากหน้ารายงาน)
    invoice_recorded_at TEXT,                           -- วันเวลาที่กดบันทึก
    invoice_recorded_by INT,                             -- ผู้ใช้ที่กดบันทึก
    channel             VARCHAR(20) NOT NULL DEFAULT 'online_report',  -- 'online_report' = แจ้งซ่อมออนไลน์ทันที (ไม่ระบุวันนัด)
                                                                         -- 'booking' = จองวันเวลาเข้ารับบริการล่วงหน้า
    booking_date        TEXT,     -- วันที่นัดหมายเข้ารับบริการ (YYYY-MM-DD) — NULL ถ้าไม่ได้จองคิว (channel='online_report')
    booking_time_slot   TEXT,     -- ช่วงเวลานัดหมาย (เช่น '09:00-10:00') — NULL ถ้าไม่ได้จองคิว
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (assigned_tech_id) REFERENCES Users(user_id),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (invoice_recorded_by) REFERENCES Users(user_id),
    CONSTRAINT chk_tickets_status CHECK (status IN ('New','Diagnosing','Waiting for Parts','In Repair','Testing','Resolved/Closed')),
    CONSTRAINT chk_tickets_channel CHECK (channel IN ('online_report','booking'))
);

CREATE TABLE IF NOT EXISTS Ticket_Media (
    media_id      SERIAL PRIMARY KEY,
    ticket_id     INT NOT NULL,
    media_type    VARCHAR(10) NOT NULL,   -- 'image','video'
    filename      TEXT NOT NULL,      -- ชื่อไฟล์เดิมจากลูกค้า
    stored_name   TEXT NOT NULL,      -- ชื่อไฟล์ที่เก็บจริงในดิสก์ (กันชื่อชนกัน/อันตราย)
    uploaded_at   TEXT NOT NULL,
    -- service_log_id (ผูกกับ Service_Logs เมื่อเป็นรูป/วิดีโอที่แนบมากับการบันทึกผลการซ่อม) เพิ่มผ่าน
    -- migration ใน db.py แทนที่จะใส่ในนี้ตรงๆ เพราะตาราง Service_Logs ยังไม่ถูกสร้าง ณ จุดนี้ในไฟล์
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    CONSTRAINT chk_ticket_media_media_type CHECK (media_type IN ('image','video'))
);

-- ประวัติการเปลี่ยนสถานะของใบงานซ่อมทุกใบ (สร้างตั๋ว/เปลี่ยนสถานะ/มอบหมายช่างใหม่) — เก็บไว้ตรวจสอบย้อนหลังว่า
-- ใครทำอะไรเมื่อไร ใช้แสดงเป็นไทม์ไลน์บนหน้ารายละเอียดตั๋ว (ทั้งฝั่งลูกค้าและฝั่งเจ้าหน้าที่)
CREATE TABLE IF NOT EXISTS Ticket_Status_History (
    history_id   SERIAL PRIMARY KEY,
    ticket_id    INT NOT NULL,
    from_status  VARCHAR(30),   -- NULL = แถวแรกตอนสร้างตั๋ว (ยังไม่มีสถานะก่อนหน้า)
    to_status    VARCHAR(30) NOT NULL,
    changed_by   INT,           -- Users.user_id ของผู้ทำรายการ (NULL = ลูกค้าเองตอนแจ้ง/จองซ่อม ไม่มีบัญชี staff เกี่ยวข้อง)
    note         TEXT,          -- หมายเหตุเพิ่มเติม เช่น "มอบหมายช่าง: สมชาย" (ไม่บังคับ)
    changed_at   TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (changed_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS Spare_Parts (
    part_sku           VARCHAR(32) PRIMARY KEY,
    part_name          TEXT NOT NULL,
    compatible_models  TEXT,
    stock_quantity     INT NOT NULL DEFAULT 0,
    cost_price         DOUBLE PRECISION NOT NULL DEFAULT 0,
    labor_fee          DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ค่าบริการเปลี่ยนอุปกรณ์มาตรฐานของอะไหล่ชิ้นนี้
    commission_fee     DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ค่าคอมมิชชั่นที่จ่ายให้ช่าง/ผู้ขายต่อการเบิกอะไหล่ชิ้นนี้ 1 ครั้ง
    center_id           INT,                        -- ศูนย์บริการที่เก็บสินค้าชิ้นนี้ (ไม่ระบุ = คลังกลาง/ใช้ร่วมกันทุกสาขา)
    reorder_level      INT NOT NULL DEFAULT 0,
    image_filename     TEXT,                       -- ชื่อไฟล์รูปอะไหล่ (1 รูปต่อชิ้น) เก็บจริงใน uploads/parts/
    category           VARCHAR(20) NOT NULL DEFAULT 'Spare_Part',  -- 'FDM_Printer','Resin_Printer','Spare_Part','Material','Other' — ประเภทสินค้า ใช้จัดกลุ่มแสดงผลหน้าแรก
    description        TEXT,  -- รายละเอียดสินค้า แสดงในหน้าคลังสินค้า (แอดมิน/ผู้จัดการ) และ popup สอบถามสินค้าบนหน้าแรกสาธารณะ
    ownership          VARCHAR(20) NOT NULL DEFAULT 'owned',
                        -- 'consignment' = สต็อกฝากขายจาก HQ (ศูนย์บริการยังไม่ได้เป็นเจ้าของจนกว่าจะขายได้ ต้องรายงานยอด/ชำระเงินคืน HQ)
                        -- 'owned' = สต็อกที่ศูนย์บริการซื้อ/เป็นเจ้าของแล้ว (พฤติกรรมเดิมของระบบก่อนมีฟีเจอร์นี้)
    odoo_product_id    INT,  -- id ของ product.template ฝั่ง Odoo หลังซิงก์สำเร็จ (NULL = ยังไม่เคยซิงก์)
    storage_location   TEXT,  -- ตำแหน่งจัดเก็บสินค้าภายในคลัง (เช่น "ชั้น A3", "ตู้ 2 ช่อง 5") — ไม่บังคับกรอก ช่วยหาสินค้าเจอเร็วขึ้น
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    CONSTRAINT chk_spare_parts_category CHECK (category IN ('FDM_Printer','Resin_Printer','Spare_Part','Material','Other')),
    CONSTRAINT chk_spare_parts_ownership CHECK (ownership IN ('owned','consignment'))
);

-- รูปสินค้าเพิ่มเติม (นอกเหนือจาก image_filename ซึ่งเป็นรูปปกหลัก) — รวมกันได้สูงสุด 9 รูปต่อสินค้า
-- (จำกัดฝั่งแอปพลิเคชัน ไม่ใช่ระดับฐานข้อมูล) ใช้แสดงเป็นแกลเลอรีที่หน้าแรกสาธารณะ (รูปหลักใหญ่ + รูปย่อยด้านล่าง)
CREATE TABLE IF NOT EXISTS Part_Images (
    image_id     SERIAL PRIMARY KEY,
    part_sku     VARCHAR(32) NOT NULL,
    stored_name  TEXT NOT NULL,          -- ชื่อไฟล์ที่เก็บจริงในดิสก์ (เก็บใน uploads/parts/ เหมือนรูปปกสินค้า)
    uploaded_at  TEXT NOT NULL,
    FOREIGN KEY (part_sku) REFERENCES Spare_Parts(part_sku)
);

CREATE TABLE IF NOT EXISTS Service_Logs (
    log_id           SERIAL PRIMARY KEY,
    ticket_id        INT NOT NULL,
    part_sku_used    VARCHAR(32),
    quantity_used    INT DEFAULT 0,
    action_taken     TEXT,
    tech_notes       TEXT,
    labor_fee        DOUBLE PRECISION NOT NULL DEFAULT 0,        -- ค่าบริการเปลี่ยนอุปกรณ์ที่เรียกเก็บจริง (ช่างปรับได้ต่องาน)
    is_claim         SMALLINT NOT NULL DEFAULT 0,    -- เคลมประกัน — ถ้า 1 ราคาอะไหล่จะเป็น 0 บาทเสมอในใบเสนอราคา/ใบแจ้งหนี้ (ยังคงคิดค่าบริการตามปกติ)
    approval_status  VARCHAR(20) NOT NULL DEFAULT 'auto',  -- 'auto','pending','approved','rejected'
    created_at       TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (part_sku_used) REFERENCES Spare_Parts(part_sku),
    CONSTRAINT chk_service_logs_approval_status CHECK (approval_status IN ('auto','pending','approved','rejected'))
);

-- ---------------------------------------------------------------- การแจ้งชำระเงิน --
-- ลูกค้า (หรือ staff แทนลูกค้า) แจ้งชำระเงินพร้อมแนบรูปสลิปโอนเงิน แล้วรอ staff (แอดมิน/ผู้จัดการ/ช่าง
-- ที่ดูแลตั๋วนี้) ตรวจสอบและยืนยัน — เมื่อยืนยันแล้วจึงจะออกใบเสร็จรับเงิน (receipt) ได้
CREATE TABLE IF NOT EXISTS Payments (
    payment_id     SERIAL PRIMARY KEY,
    ticket_id      INT NOT NULL,
    amount         DOUBLE PRECISION NOT NULL DEFAULT 0,
    slip_filename  TEXT NOT NULL,        -- ชื่อไฟล์รูปสลิปที่เก็บจริง (เก็บร่วมโฟลเดอร์กับ Ticket_Media ของตั๋วนี้)
    notified_by    INT,                  -- Users.user_id ของผู้แจ้ง (NULL ได้ถ้าลูกค้าไม่มีบัญชี/staff คีย์แทน)
    status         VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 'pending','confirmed','rejected'
    confirmed_by   INT,                  -- Users.user_id ของ staff ที่ตรวจสอบ/ยืนยัน
    confirmed_at   TEXT,
    created_at     TEXT NOT NULL,
    notes          TEXT,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (notified_by) REFERENCES Users(user_id),
    FOREIGN KEY (confirmed_by) REFERENCES Users(user_id),
    CONSTRAINT chk_payments_status CHECK (status IN ('pending','confirmed','rejected'))
);

CREATE TABLE IF NOT EXISTS Quotations (
    quote_id     SERIAL PRIMARY KEY,
    ticket_id    INT NOT NULL,
    created_by   INT NOT NULL,   -- Users.user_id ของช่างที่ออกใบเสนอราคา
    created_at   TEXT NOT NULL,
    notes        TEXT,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS Quotation_Items (
    item_id      SERIAL PRIMARY KEY,
    quote_id     INT NOT NULL,
    description  TEXT NOT NULL,
    quantity     DOUBLE PRECISION NOT NULL DEFAULT 1,
    unit_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    tech_notes   TEXT,             -- คัดลอกหมายเหตุช่างจากประวัติการซ่อม (Service_Logs) มาแสดงต่อท้ายรายการในใบเสนอราคา
    FOREIGN KEY (quote_id) REFERENCES Quotations(quote_id)
);

-- ---------------------------------------------------------------- ขายสินค้า --
-- ศูนย์บริการที่ sells_products=1 เท่านั้นที่บันทึกการขายได้ (บังคับใน app.py ไม่ใช่ที่ชั้น DB)

CREATE TABLE IF NOT EXISTS Sales_Orders (
    order_id     SERIAL PRIMARY KEY,
    center_id    INT NOT NULL,   -- สาขาที่ขาย
    sold_by      INT NOT NULL,   -- Users.user_id ของพนักงานขาย (role='sales' หรือ admin/manager ก็บันทึกแทนได้)
    customer_id  INT,            -- ลูกค้า (ไม่บังคับ เผื่อขายหน้าร้านแบบไม่ผูกบัญชี)
    created_at   TEXT NOT NULL,
    notes        TEXT,
    payment_confirmed_at TEXT,        -- วันที่ยืนยันรับชำระเงินเข้าระบบ (NULL = ยังไม่ยืนยัน/ยังไม่ออกบิล)
    payment_confirmed_by INT,         -- Users.user_id ของพนักงานที่กดยืนยันรับชำระ
    payment_doc_type     VARCHAR(20), -- เอกสารที่ใช้ตอนยืนยันรับชำระ: 'cash_bill' หรือ 'tax_invoice'
    cancelled_at         TEXT,        -- วันที่ยกเลิกรายการขายนี้ (NULL = ยังไม่ยกเลิก) — ยกเลิกได้แม้ยืนยันรับชำระไปแล้ว
                                       -- (ต่างจากลบทั้งบิล ตรงที่ยังเก็บประวัติไว้ตรวจสอบย้อนหลังได้ ไม่ได้ลบทิ้งจริง)
    cancelled_by         INT,         -- Users.user_id ของแอดมินที่กดยกเลิก (เฉพาะแอดมินเท่านั้นที่ยกเลิกได้)
    cancel_reason        TEXT,        -- เหตุผลการยกเลิก ไม่บังคับกรอก
    channel              VARCHAR(30) NOT NULL DEFAULT 'หน้าร้าน',  -- ช่องทางการขาย: หน้าร้าน/Shopee/Lazada/Thaimart/Facebook/TikTok/TDPrinter
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (sold_by) REFERENCES Users(user_id),
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id),
    FOREIGN KEY (payment_confirmed_by) REFERENCES Users(user_id),
    FOREIGN KEY (cancelled_by) REFERENCES Users(user_id),
    CONSTRAINT chk_sales_orders_payment_doc_type CHECK (payment_doc_type IS NULL OR payment_doc_type IN ('cash_bill','tax_invoice')),
    CONSTRAINT chk_sales_orders_channel CHECK (channel IN ('หน้าร้าน','Shopee','Lazada','Thaimart','Facebook','TikTok','TDPrinter'))
);

CREATE TABLE IF NOT EXISTS Sale_Items (
    item_id          SERIAL PRIMARY KEY,
    order_id         INT NOT NULL,
    part_sku         VARCHAR(32) NOT NULL,
    quantity         INT NOT NULL DEFAULT 1,
    unit_price       DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ราคาขายจริงต่อหน่วย ณ ตอนขาย
    commission_fee   DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ค่าคอมมิชชั่นต่อหน่วย snapshot จาก Spare_Parts ตอนขาย
                                                  -- (กันย้อนหลังถ้าค่าคอมมิชชั่นมาตรฐานถูกแก้ไขทีหลัง)
    FOREIGN KEY (order_id) REFERENCES Sales_Orders(order_id),
    FOREIGN KEY (part_sku) REFERENCES Spare_Parts(part_sku)
);

-- ------------------------------------------- ขั้นตอนการทำงานพาร์ตเนอร์ TDPrinter --
-- (HQ = แอดมิน, ศูนย์บริการ = ผู้จัดการ) ครอบคลุม 5 ขั้นตอน: (1) ฝากขายเครื่องพิมพ์ 3 มิติ,
-- (2) จัดหาวัสดุ/เส้นพลาสติก, (3) กระจายอะไหล่ — ทั้ง 3 อย่างนี้ใช้ Spare_Parts.ownership เป็นตัวบอกสถานะ
-- ฝากขาย/สต็อกของศูนย์เอง, (4) สั่งซื้อ/ติดตามสถานะ (Restock_Orders), (5) รายงานยอดขาย/ชำระเงิน
-- ฝากขายรายเดือน (Consignment_Settlements)

CREATE TABLE IF NOT EXISTS Restock_Orders (
    order_id          SERIAL PRIMARY KEY,
    center_id         INT NOT NULL,           -- ศูนย์บริการที่สั่งซื้อ
    requested_by      INT NOT NULL,           -- Users.user_id ของผู้จัดการที่กดสั่งซื้อ
    status            VARCHAR(20) NOT NULL DEFAULT 'requested',  -- 'requested','processing','shipped','received','cancelled'
    tracking_number   VARCHAR(100),           -- หมายเลขติดตามพัสดุ (HQ กรอกตอนยืนยันจัดส่ง)
    notes             TEXT,
    created_at        TEXT NOT NULL,
    processed_at      TEXT,
    shipped_at        TEXT,
    received_at       TEXT,
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (requested_by) REFERENCES Users(user_id),
    CONSTRAINT chk_restock_orders_status CHECK (status IN ('requested','processing','shipped','received','cancelled'))
);

CREATE TABLE IF NOT EXISTS Restock_Order_Items (
    item_id              SERIAL PRIMARY KEY,
    order_id             INT NOT NULL,
    part_sku             VARCHAR(32) NOT NULL,
    quantity_requested   INT NOT NULL DEFAULT 1,
    quantity_received    INT,                 -- NULL จนกว่าศูนย์บริการจะกดยืนยันรับของ
    unit_price           DOUBLE PRECISION NOT NULL DEFAULT 0,  -- ราคาต่อหน่วย ใช้แสดงยอดเงินบนใบส่งสินค้า
                                                                -- (ค่าเริ่มต้นมาจาก Spare_Parts.cost_price ตอนสร้าง แก้ไขได้)
    FOREIGN KEY (order_id) REFERENCES Restock_Orders(order_id),
    FOREIGN KEY (part_sku) REFERENCES Spare_Parts(part_sku)
);

CREATE TABLE IF NOT EXISTS Consignment_Settlements (
    settlement_id           SERIAL PRIMARY KEY,
    center_id                INT NOT NULL,
    period_month             VARCHAR(7) NOT NULL,   -- รูปแบบ 'YYYY-MM' เดือนที่รายงานยอดขาย
    total_consignment_sales  DOUBLE PRECISION NOT NULL DEFAULT 0,  -- คำนวณอัตโนมัติจากยอดขายสินค้าฝากขาย (ownership='consignment') ในเดือนนั้น
    status                   VARCHAR(20) NOT NULL DEFAULT 'draft',  -- 'draft','submitted','reconciled','paid'
    invoice_number           VARCHAR(64),
    notes                    TEXT,
    submitted_by             INT,             -- Users.user_id ของผู้จัดการที่กดส่งรายงาน
    reconciled_by            INT,             -- Users.user_id ของแอดมินที่ตรวจสอบกระทบยอด
    submitted_at             TEXT,
    reconciled_at            TEXT,
    paid_at                  TEXT,
    CONSTRAINT uniq_center_period UNIQUE (center_id, period_month),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (submitted_by) REFERENCES Users(user_id),
    FOREIGN KEY (reconciled_by) REFERENCES Users(user_id),
    CONSTRAINT chk_consignment_settlements_status CHECK (status IN ('draft','submitted','reconciled','paid'))
);

-- ------------------------------------------------------ ทรัพยากรโปรโมท (HQ -> ศูนย์บริการ) --
-- แอดมิน (HQ) อัปโหลด/แนบทรัพยากรไว้ให้ศูนย์บริการ (ผู้จัดการ/เซล) ดาวน์โหลดไปใช้โปรโมทหน้าร้าน/โซเชียล
-- 'Brochure' และ 'Document' เก็บเป็นไฟล์จริง (รูปภาพ/PDF) ส่วน 'Video' เก็บเป็นลิงก์ภายนอก (YouTube/Facebook/
-- Google Drive ฯลฯ) ไม่อัปโหลดไฟล์วิดีโอเข้าระบบตรงๆ เพื่อไม่ให้ดิสก์เซิร์ฟเวอร์เต็ม
CREATE TABLE IF NOT EXISTS Marketing_Resources (
    resource_id     SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,
    resource_type   VARCHAR(20) NOT NULL,  -- 'Brochure','Document','Video'
    file_filename   TEXT,                  -- ชื่อไฟล์ที่เก็บจริง (เฉพาะ Brochure/Document) เก็บใน uploads/marketing/
    video_url       TEXT,                  -- ลิงก์วิดีโอภายนอก (เฉพาะ Video)
    uploaded_by     INT NOT NULL,          -- Users.user_id ของแอดมินที่อัปโหลด
    created_at      TEXT NOT NULL,
    FOREIGN KEY (uploaded_by) REFERENCES Users(user_id),
    CONSTRAINT chk_marketing_resources_type CHECK (resource_type IN ('Brochure','Document','Video'))
);

-- ------------------------------------------------------------------------- ShareSpace --
-- โมดูลใหม่แทนที่ "ทรัพยากรโปรโมท" เดิมด้านบน (ตารางเดิมยังคงอยู่ ไม่ลบข้อมูลเก่า แต่ไม่มีเมนูเข้าถึงแล้ว)
-- แอดมินสร้าง "กิจกรรม" (Activity) 1 รายการ — ตั้งแต่เวอร์ชันนี้เป็นต้นไป แต่ละกิจกรรมผูกกับหมวดเดียว
-- (category) ตั้งแต่ตอนสร้าง เพื่อให้กำหนดสิทธิ์ชัดเจน แยกกิจกรรม Marketing กับ Technical ออกจากกันเด็ดขาด:
--   'marketing'  = สื่อสำหรับฝ่ายขาย/ลูกค้า (ภาพสินค้า โบรชัวร์ วิดีโอ ฯลฯ) — manager/sales เห็นได้
--   'technical'  = เอกสารเฉพาะทีมเทคนิค (คู่มือติดตั้ง เอกสารระบบ ฯลฯ) — เห็นเฉพาะ technician (และ admin)
-- category เป็น NULL ได้เฉพาะกิจกรรมเก่าที่สร้างไว้ก่อนแยกหมวด (มีไฟล์ผสมทั้งสองหมวดในกิจกรรมเดียว — ยังแก้ไขได้
-- ตามปกติผ่านฟอร์มแบบเดิมที่แสดงทั้งสองส่วน) กิจกรรมที่สร้างใหม่ต้องระบุ category เสมอ
-- กิจกรรมมีสถานะ 'draft' (ฉบับร่าง แก้ไขได้ ยังไม่มีใครเห็นนอกจากแอดมิน) / 'published' (เผยแพร่แล้ว)
CREATE TABLE IF NOT EXISTS Activities (
    activity_id             SERIAL PRIMARY KEY,
    title                   TEXT NOT NULL,
    category                VARCHAR(20),      -- 'marketing' | 'technical' | NULL (กิจกรรมเก่าก่อนแยกหมวด)
    event_date              TEXT,             -- วันที่จัดกิจกรรม (YYYY-MM-DD) ไม่บังคับ
    download_deadline       TEXT,             -- กำหนดปิดดาวน์โหลด (YYYY-MM-DD) ไม่บังคับ — เลยวันนี้แล้วซ่อนจากหน้า ShareSpace
    marketing_description   TEXT,             -- คำอธิบายสั้นๆ ของชุดไฟล์ Marketing
    technical_description   TEXT,             -- คำอธิบายสั้นๆ ของชุดไฟล์ Technical
    status                  VARCHAR(20) NOT NULL DEFAULT 'draft',
    is_public               SMALLINT NOT NULL DEFAULT 0,   -- 1 = ใครก็ตามที่มีลิงก์ /s/<activity_id> ดู/ดาวน์โหลด
                                                            -- ไฟล์ได้โดยไม่ต้อง login (ทั้งหมวด marketing และ technical)
    created_by              INT,
    created_at              TEXT NOT NULL,
    published_at            TEXT,
    FOREIGN KEY (created_by) REFERENCES Users(user_id),
    CONSTRAINT chk_activities_status CHECK (status IN ('draft','published')),
    CONSTRAINT chk_activities_category CHECK (category IS NULL OR category IN ('marketing','technical'))
);

CREATE TABLE IF NOT EXISTS Activity_Files (
    file_id         SERIAL PRIMARY KEY,
    activity_id     INT NOT NULL,
    category        VARCHAR(20) NOT NULL,   -- 'marketing' | 'technical'
    filename        TEXT NOT NULL,          -- ชื่อไฟล์ต้นฉบับ (แสดงผล/ตั้งชื่อตอนดาวน์โหลด)
    stored_name     TEXT NOT NULL,          -- ชื่อไฟล์จริงบนดิสก์ใน uploads/activities/
    size_bytes      INT,
    uploaded_by     INT,
    uploaded_at     TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES Activities(activity_id),
    FOREIGN KEY (uploaded_by) REFERENCES Users(user_id),
    CONSTRAINT chk_activity_files_category CHECK (category IN ('marketing','technical'))
);
