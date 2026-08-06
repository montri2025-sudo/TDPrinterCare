-- ระบบบริหารจัดการงานซ่อม (Repair Ticketing System) — MySQL schema
-- หมายเหตุ: ลำดับตารางถูกจัดใหม่ให้ FOREIGN KEY อ้างอิงตารางที่ถูกสร้างไปแล้วเสมอ
-- (MySQL/InnoDB ต้องมีตารางปลายทางอยู่ก่อน ต่างจาก SQLite ที่ไม่บังคับลำดับนี้)

CREATE TABLE IF NOT EXISTS Service_Centers (
    center_id      INT AUTO_INCREMENT PRIMARY KEY,
    name           TEXT NOT NULL,
    address        TEXT,
    phone          TEXT,
    latitude       DOUBLE,   -- พิกัดสำหรับปักหมุดบนแผนที่ (ไม่บังคับ)
    longitude      DOUBLE,
    supports_fdm   TINYINT NOT NULL DEFAULT 1,  -- รับซ่อมเครื่องพิมพ์ประเภท FDM
    supports_resin TINYINT NOT NULL DEFAULT 1,  -- รับซ่อมเครื่องพิมพ์ประเภท Resin
    sells_products TINYINT NOT NULL DEFAULT 0   -- สาขานี้จำหน่ายสินค้า (ขายหน้าร้าน) ได้ด้วยหรือไม่
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Customers (
    customer_id  INT AUTO_INCREMENT PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT,
    email        TEXT,
    line_id      TEXT,
    address      TEXT,
    tax_id       VARCHAR(20),  -- เลขประจำตัวผู้เสียภาษี (13 หลัก) ใช้ออกใบกำกับภาษี — ไม่บังคับกรอก
    latitude     DOUBLE,   -- พิกัดที่อยู่ลูกค้า (ไม่บังคับ) — ใช้ปักหมุดบนแผนที่ Dashboard ภายใน (แอดมิน/ผู้จัดการเท่านั้น)
    longitude    DOUBLE,
    device_quota INT NOT NULL DEFAULT 3  -- จำนวนเครื่องพิมพ์สูงสุดที่ลูกค้าลงทะเบียนเองได้ (ตอนสมัคร/หน้า self-service) — แอดมินปรับเพิ่มได้ต่อลูกค้า
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Users (
    user_id      INT AUTO_INCREMENT PRIMARY KEY,
    username     VARCHAR(64) UNIQUE NOT NULL,
    password     VARCHAR(255) NOT NULL,             -- PBKDF2-HMAC-SHA256 hash + salt (ดู db.hash_password)
    role         ENUM('customer','admin','technician','manager','sales') NOT NULL,
    name         TEXT NOT NULL,
    phone        VARCHAR(32),                        -- เบอร์โทรติดต่อของพนักงาน (แสดงบนหน้าแรกสาธารณะสำหรับผู้จัดการ/เซล) / เบอร์มือถือลูกค้าที่สมัครผ่าน Google/LINE
    customer_id  INT,                                -- only set when role = 'customer'
    center_id    INT,                                -- ศูนย์บริการที่ผู้ใช้งานสังกัด (สำหรับ staff)
    is_active    TINYINT NOT NULL DEFAULT 1,          -- 0 = ระงับการใช้งาน (soft delete)
    auth_provider ENUM('local','google','line') NOT NULL DEFAULT 'local',  -- วิธีสมัคร/ล็อกอิน — 'local' คือตั้งชื่อผู้ใช้/รหัสผ่านเอง (staff ทุกคนและลูกค้าที่แอดมินสร้างให้)
    oauth_sub     VARCHAR(255),                       -- รหัสผู้ใช้ที่ Google/LINE ออกให้ (sub/userId) — ใช้จับคู่บัญชีตอนล็อกอินซ้ำ
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    UNIQUE KEY uniq_oauth_account (auth_provider, oauth_sub)  -- กันสมัครซ้ำบัญชี Google/LINE เดียวกัน (NULL หลายแถวได้ปกติสำหรับบัญชี local)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Devices (
    device_sn         VARCHAR(64) PRIMARY KEY,
    customer_id       INT NOT NULL,
    model             TEXT NOT NULL,
    type              ENUM('FDM','Resin','Wash & Cure','Other'),
    purchase_date     TEXT,
    warranty_end_date TEXT,
    status            ENUM('Active','Decommissioned','Sold') NOT NULL DEFAULT 'Active',  -- ใช้งานอยู่/เลิกใช้แล้ว/ขายต่อแล้ว — เครื่องที่ไม่ Active จะไม่ขึ้นในรายการแจ้งซ่อมใหม่/แจ้งเตือนบำรุงรักษาอีก
    created_at        TEXT,  -- วันที่ลงทะเบียนเครื่องในระบบ ใช้เรียงเครื่องที่เพิ่มล่าสุดขึ้นก่อนในตารางเครื่องพิมพ์ (เครื่องเก่าก่อนมีคอลัมน์นี้จะเป็น NULL)
    total_usage_hours DOUBLE NOT NULL DEFAULT 0,  -- ชั่วโมงการทำงานสะสม — ลูกค้า/ช่างกรอกเองตอนเริ่มงานพิมพ์แต่ละครั้ง (ไม่มีการเชื่อมต่อฮาร์ดแวร์) ใช้คำนวณรอบบำรุงรักษาแบบชั่วโมง
    purchase_proof_filename TEXT,  -- ชื่อไฟล์หลักฐานการสั่งซื้อ (รูปภาพ/PDF) ที่ลูกค้าแนบตอนลงทะเบียนเครื่องเอง — เก็บจริงใน uploads/device_proof/<sn>/
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------- บำรุงรักษา --
-- แผนบำรุงรักษา (Maintenance Scheduler) — งานบำรุงรักษาที่ต้องทำเป็นระยะ กำหนดโดยแอดมิน
-- ผูกกับประเภทเครื่อง (NULL = ใช้กับทุกประเภท) รอบคำนวณได้ 2 แบบ: ตามวัน (สัปดาห์/เดือน) หรือตามชั่วโมงใช้งานสะสม
CREATE TABLE IF NOT EXISTS Maintenance_Plan_Items (
    plan_item_id   INT AUTO_INCREMENT PRIMARY KEY,
    device_type    ENUM('FDM','Resin','Wash & Cure','Other'),  -- NULL = ใช้กับเครื่องพิมพ์ทุกประเภท
    task_name      TEXT NOT NULL,        -- เช่น "ทาจาระบีแกน X/Y/Z", "เปลี่ยนหัวฉีด"
    interval_type  ENUM('days','hours') NOT NULL DEFAULT 'days',
    interval_value INT NOT NULL,         -- จำนวนวัน (เช่น 7, 30) หรือชั่วโมง (เช่น 50, 200, 500) ตาม interval_type
    is_active      TINYINT(1) NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- รายการตรวจสอบก่อนพิมพ์ทุกครั้ง (Checklist) — บังคับติ๊กครบทุกข้อก่อนเริ่มงานพิมพ์ได้ (ดู Print_Sessions)
CREATE TABLE IF NOT EXISTS Checklist_Items (
    checklist_item_id INT AUTO_INCREMENT PRIMARY KEY,
    device_type       ENUM('FDM','Resin','Wash & Cure','Other'),  -- NULL = ใช้กับเครื่องพิมพ์ทุกประเภท
    label             TEXT NOT NULL,      -- เช่น "ทำความสะอาดฐานพิมพ์ (Bed)"
    sort_order        INT NOT NULL DEFAULT 0,
    is_active         TINYINT(1) NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- บันทึก "เริ่มงานพิมพ์" แต่ละครั้ง — ต้องติ๊ก Checklist ครบก่อนจึงจะบันทึกได้ (บังคับ "ก่อนพิมพ์ทุกครั้ง")
-- ชั่วโมงที่ประเมิน (estimated_hours) จะถูกบวกสะสมเข้า Devices.total_usage_hours ทันทีที่บันทึก
CREATE TABLE IF NOT EXISTS Print_Sessions (
    session_id         INT AUTO_INCREMENT PRIMARY KEY,
    device_sn          VARCHAR(64) NOT NULL,
    started_by         INT,                 -- Users.user_id ของผู้เริ่มงาน (ลูกค้าเจ้าของเครื่อง หรือช่าง/staff)
    checklist_snapshot TEXT,                -- JSON list ของรายการ Checklist ที่ติ๊กไว้ ณ ตอนนั้น (เก็บสำเนาไว้ แม้ Checklist_Items จะถูกแก้ไขภายหลัง)
    estimated_hours    DOUBLE NOT NULL DEFAULT 0,  -- ชั่วโมงที่ประเมินว่าจะใช้พิมพ์งานนี้ (ลูกค้า/ช่างกรอกเอง)
    job_note           TEXT,                -- รายละเอียดงานพิมพ์ (ไม่บังคับ)
    created_at         TEXT NOT NULL,
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (started_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ประวัติการเข้าบำรุงรักษาเครื่องพิมพ์ตามรอบ (นอกเหนือจากการแจ้งซ่อมปกติ) — ลูกค้าเองก็บันทึกได้ (self-service)
-- ไม่ใช่แค่ staff เท่านั้น — plan_item_id ผูกกับงานบำรุงรักษาตามแผน (NULL = บันทึกอิสระแบบเดิม)
CREATE TABLE IF NOT EXISTS Maintenance_Logs (
    maintenance_id       INT AUTO_INCREMENT PRIMARY KEY,
    device_sn            VARCHAR(64) NOT NULL,
    plan_item_id         INT,                 -- Maintenance_Plan_Items.plan_item_id ที่ทำ (NULL = บันทึกอิสระ ไม่ผูกแผน)
    performed_at         TEXT NOT NULL,       -- วันที่เข้าบำรุงรักษา (YYYY-MM-DD)
    hours_at_maintenance DOUBLE,              -- ชั่วโมงใช้งานสะสมของเครื่อง ณ ตอนบำรุงรักษาครั้งนี้ (snapshot ใช้คำนวณรอบถัดไปแบบชั่วโมง)
    parts_replaced       TEXT,                -- อะไหล่ที่เปลี่ยนไปในการบำรุงรักษาครั้งนี้ (ไม่บังคับ)
    notes                TEXT,
    performed_by         INT,                 -- Users.user_id ของผู้บันทึก (nullable — เผื่อบันทึกย้อนหลัง/ไม่ทราบผู้ทำ, อาจเป็นลูกค้าเองหรือ staff)
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (plan_item_id) REFERENCES Maintenance_Plan_Items(plan_item_id),
    FOREIGN KEY (performed_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- การแจ้งเตือน (Alert & Notification) — สร้างขึ้นทั้งแบบแจ้งในระบบ (in-app) และพยายามส่งอีเมลควบคู่กัน
-- (ถ้าตั้งค่า SMTP_* ไว้) เมื่อเครื่องถึงรอบบำรุงรักษา — ดู _sync_maintenance_notifications() ใน app.py
CREATE TABLE IF NOT EXISTS Notifications (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id          INT NOT NULL,        -- ผู้รับ (เจ้าของเครื่อง หรือ staff ที่เกี่ยวข้อง)
    device_sn        VARCHAR(64),
    plan_item_id     INT,                 -- Maintenance_Plan_Items.plan_item_id ที่แจ้งเตือนนี้เกี่ยวข้อง (ใช้กันแจ้งซ้ำงานเดิม)
    category         ENUM('maintenance_due','general') NOT NULL DEFAULT 'maintenance_due',
    title            TEXT NOT NULL,
    message          TEXT NOT NULL,
    is_read          TINYINT(1) NOT NULL DEFAULT 0,
    email_sent       TINYINT(1) NOT NULL DEFAULT 0,
    email_error      TEXT,
    created_at       TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (plan_item_id) REFERENCES Maintenance_Plan_Items(plan_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Tickets (
    ticket_id        INT AUTO_INCREMENT PRIMARY KEY,
    device_sn        VARCHAR(64) NOT NULL,
    issue_category   TEXT,
    description      TEXT,
    center_id        INT,                             -- สาขาที่ลูกค้าเลือกเข้ารับบริการ
    status           ENUM('New','Diagnosing','Waiting for Parts','In Repair','Testing','Resolved/Closed')
                     NOT NULL DEFAULT 'New',
    assigned_tech_id INT,
    created_at       TEXT NOT NULL,
    closed_at        TEXT,
    csat_score       INT,
    csat_comment     TEXT,
    invoice_recorded    TINYINT(1) NOT NULL DEFAULT 0,  -- ลงบันทึกใบแจ้งหนี้นี้ในบัญชี/ระบบภายนอกแล้วหรือยัง (ติ๊กจากหน้ารายงาน)
    invoice_recorded_at TEXT,                           -- วันเวลาที่กดบันทึก
    invoice_recorded_by INT,                             -- ผู้ใช้ที่กดบันทึก
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (assigned_tech_id) REFERENCES Users(user_id),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (invoice_recorded_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Ticket_Media (
    media_id      INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id     INT NOT NULL,
    media_type    ENUM('image','video') NOT NULL,
    filename      TEXT NOT NULL,      -- ชื่อไฟล์เดิมจากลูกค้า
    stored_name   TEXT NOT NULL,      -- ชื่อไฟล์ที่เก็บจริงในดิสก์ (กันชื่อชนกัน/อันตราย)
    uploaded_at   TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Spare_Parts (
    part_sku           VARCHAR(32) PRIMARY KEY,
    part_name          TEXT NOT NULL,
    compatible_models  TEXT,
    stock_quantity     INT NOT NULL DEFAULT 0,
    cost_price         DOUBLE NOT NULL DEFAULT 0,
    labor_fee          DOUBLE NOT NULL DEFAULT 0,  -- ค่าบริการเปลี่ยนอุปกรณ์มาตรฐานของอะไหล่ชิ้นนี้
    commission_fee     DOUBLE NOT NULL DEFAULT 0,  -- ค่าคอมมิชชั่นที่จ่ายให้ช่าง/ผู้ขายต่อการเบิกอะไหล่ชิ้นนี้ 1 ครั้ง
    center_id           INT,                        -- ศูนย์บริการที่เก็บสินค้าชิ้นนี้ (ไม่ระบุ = คลังกลาง/ใช้ร่วมกันทุกสาขา)
    reorder_level      INT NOT NULL DEFAULT 0,
    image_filename     TEXT,                       -- ชื่อไฟล์รูปอะไหล่ (1 รูปต่อชิ้น) เก็บจริงใน uploads/parts/
    category           ENUM('FDM_Printer','Resin_Printer','Spare_Part','Material','Other')
                        NOT NULL DEFAULT 'Spare_Part',  -- ประเภทสินค้า ใช้จัดกลุ่มแสดงผลหน้าแรก
    description        TEXT,  -- รายละเอียดสินค้า แสดงในหน้าคลังสินค้า (แอดมิน/ผู้จัดการ) และ popup สอบถามสินค้าบนหน้าแรกสาธารณะ
    ownership          ENUM('owned','consignment') NOT NULL DEFAULT 'owned',
                        -- 'consignment' = สต็อกฝากขายจาก HQ (ศูนย์บริการยังไม่ได้เป็นเจ้าของจนกว่าจะขายได้ ต้องรายงานยอด/ชำระเงินคืน HQ)
                        -- 'owned' = สต็อกที่ศูนย์บริการซื้อ/เป็นเจ้าของแล้ว (พฤติกรรมเดิมของระบบก่อนมีฟีเจอร์นี้)
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- รูปสินค้าเพิ่มเติม (นอกเหนือจาก image_filename ซึ่งเป็นรูปปกหลัก) — รวมกันได้สูงสุด 9 รูปต่อสินค้า
-- (จำกัดฝั่งแอปพลิเคชัน ไม่ใช่ระดับฐานข้อมูล) ใช้แสดงเป็นแกลเลอรีที่หน้าแรกสาธารณะ (รูปหลักใหญ่ + รูปย่อยด้านล่าง)
CREATE TABLE IF NOT EXISTS Part_Images (
    image_id     INT AUTO_INCREMENT PRIMARY KEY,
    part_sku     VARCHAR(32) NOT NULL,
    stored_name  TEXT NOT NULL,          -- ชื่อไฟล์ที่เก็บจริงในดิสก์ (เก็บใน uploads/parts/ เหมือนรูปปกสินค้า)
    uploaded_at  TEXT NOT NULL,
    FOREIGN KEY (part_sku) REFERENCES Spare_Parts(part_sku)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Service_Logs (
    log_id           INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id        INT NOT NULL,
    part_sku_used    VARCHAR(32),
    quantity_used    INT DEFAULT 0,
    action_taken     TEXT,
    tech_notes       TEXT,
    labor_fee        DOUBLE NOT NULL DEFAULT 0,        -- ค่าบริการเปลี่ยนอุปกรณ์ที่เรียกเก็บจริง (ช่างปรับได้ต่องาน)
    is_claim         TINYINT(1) NOT NULL DEFAULT 0,    -- เคลมประกัน — ถ้า 1 ราคาอะไหล่จะเป็น 0 บาทเสมอในใบเสนอราคา/ใบแจ้งหนี้ (ยังคงคิดค่าบริการตามปกติ)
    approval_status  ENUM('auto','pending','approved','rejected') NOT NULL DEFAULT 'auto',
    created_at       TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (part_sku_used) REFERENCES Spare_Parts(part_sku)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- การแจ้งชำระเงิน --
-- ลูกค้า (หรือ staff แทนลูกค้า) แจ้งชำระเงินพร้อมแนบรูปสลิปโอนเงิน แล้วรอ staff (แอดมิน/ผู้จัดการ/ช่าง
-- ที่ดูแลตั๋วนี้) ตรวจสอบและยืนยัน — เมื่อยืนยันแล้วจึงจะออกใบเสร็จรับเงิน (receipt) ได้
CREATE TABLE IF NOT EXISTS Payments (
    payment_id     INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id      INT NOT NULL,
    amount         DOUBLE NOT NULL DEFAULT 0,
    slip_filename  TEXT NOT NULL,        -- ชื่อไฟล์รูปสลิปที่เก็บจริง (เก็บร่วมโฟลเดอร์กับ Ticket_Media ของตั๋วนี้)
    notified_by    INT,                  -- Users.user_id ของผู้แจ้ง (NULL ได้ถ้าลูกค้าไม่มีบัญชี/staff คีย์แทน)
    status         ENUM('pending','confirmed','rejected') NOT NULL DEFAULT 'pending',
    confirmed_by   INT,                  -- Users.user_id ของ staff ที่ตรวจสอบ/ยืนยัน
    confirmed_at   TEXT,
    created_at     TEXT NOT NULL,
    notes          TEXT,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (notified_by) REFERENCES Users(user_id),
    FOREIGN KEY (confirmed_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Quotations (
    quote_id     INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id    INT NOT NULL,
    created_by   INT NOT NULL,   -- Users.user_id ของช่างที่ออกใบเสนอราคา
    created_at   TEXT NOT NULL,
    notes        TEXT,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Quotation_Items (
    item_id      INT AUTO_INCREMENT PRIMARY KEY,
    quote_id     INT NOT NULL,
    description  TEXT NOT NULL,
    quantity     DOUBLE NOT NULL DEFAULT 1,
    unit_price   DOUBLE NOT NULL DEFAULT 0,
    tech_notes   TEXT,             -- คัดลอกหมายเหตุช่างจากประวัติการซ่อม (Service_Logs) มาแสดงต่อท้ายรายการในใบเสนอราคา
    FOREIGN KEY (quote_id) REFERENCES Quotations(quote_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- ขายสินค้า --
-- ศูนย์บริการที่ sells_products=1 เท่านั้นที่บันทึกการขายได้ (บังคับใน app.py ไม่ใช่ที่ชั้น DB)

CREATE TABLE IF NOT EXISTS Sales_Orders (
    order_id     INT AUTO_INCREMENT PRIMARY KEY,
    center_id    INT NOT NULL,   -- สาขาที่ขาย
    sold_by      INT NOT NULL,   -- Users.user_id ของพนักงานขาย (role='sales' หรือ admin/manager ก็บันทึกแทนได้)
    customer_id  INT,            -- ลูกค้า (ไม่บังคับ เผื่อขายหน้าร้านแบบไม่ผูกบัญชี)
    created_at   TEXT NOT NULL,
    notes        TEXT,
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (sold_by) REFERENCES Users(user_id),
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Sale_Items (
    item_id          INT AUTO_INCREMENT PRIMARY KEY,
    order_id         INT NOT NULL,
    part_sku         VARCHAR(32) NOT NULL,
    quantity         INT NOT NULL DEFAULT 1,
    unit_price       DOUBLE NOT NULL DEFAULT 0,  -- ราคาขายจริงต่อหน่วย ณ ตอนขาย
    commission_fee   DOUBLE NOT NULL DEFAULT 0,  -- ค่าคอมมิชชั่นต่อหน่วย snapshot จาก Spare_Parts ตอนขาย
                                                  -- (กันย้อนหลังถ้าค่าคอมมิชชั่นมาตรฐานถูกแก้ไขทีหลัง)
    FOREIGN KEY (order_id) REFERENCES Sales_Orders(order_id),
    FOREIGN KEY (part_sku) REFERENCES Spare_Parts(part_sku)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------- ขั้นตอนการทำงานพาร์ตเนอร์ TDPrinter --
-- (HQ = แอดมิน, ศูนย์บริการ = ผู้จัดการ) ครอบคลุม 5 ขั้นตอน: (1) ฝากขายเครื่องพิมพ์ 3 มิติ,
-- (2) จัดหาวัสดุ/เส้นพลาสติก, (3) กระจายอะไหล่ — ทั้ง 3 อย่างนี้ใช้ Spare_Parts.ownership เป็นตัวบอกสถานะ
-- ฝากขาย/สต็อกของศูนย์เอง, (4) สั่งซื้อ/ติดตามสถานะ (Restock_Orders), (5) รายงานยอดขาย/ชำระเงิน
-- ฝากขายรายเดือน (Consignment_Settlements)

CREATE TABLE IF NOT EXISTS Restock_Orders (
    order_id          INT AUTO_INCREMENT PRIMARY KEY,
    center_id         INT NOT NULL,           -- ศูนย์บริการที่สั่งซื้อ
    requested_by      INT NOT NULL,           -- Users.user_id ของผู้จัดการที่กดสั่งซื้อ
    status            ENUM('requested','processing','shipped','received','cancelled')
                        NOT NULL DEFAULT 'requested',
    tracking_number   VARCHAR(100),           -- หมายเลขติดตามพัสดุ (HQ กรอกตอนยืนยันจัดส่ง)
    notes             TEXT,
    created_at        TEXT NOT NULL,
    processed_at      TEXT,
    shipped_at        TEXT,
    received_at       TEXT,
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (requested_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Restock_Order_Items (
    item_id              INT AUTO_INCREMENT PRIMARY KEY,
    order_id             INT NOT NULL,
    part_sku             VARCHAR(32) NOT NULL,
    quantity_requested   INT NOT NULL DEFAULT 1,
    quantity_received    INT,                 -- NULL จนกว่าศูนย์บริการจะกดยืนยันรับของ
    FOREIGN KEY (order_id) REFERENCES Restock_Orders(order_id),
    FOREIGN KEY (part_sku) REFERENCES Spare_Parts(part_sku)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Consignment_Settlements (
    settlement_id           INT AUTO_INCREMENT PRIMARY KEY,
    center_id                INT NOT NULL,
    period_month             VARCHAR(7) NOT NULL,   -- รูปแบบ 'YYYY-MM' เดือนที่รายงานยอดขาย
    total_consignment_sales  DOUBLE NOT NULL DEFAULT 0,  -- คำนวณอัตโนมัติจากยอดขายสินค้าฝากขาย (ownership='consignment') ในเดือนนั้น
    status                   ENUM('draft','submitted','reconciled','paid') NOT NULL DEFAULT 'draft',
    invoice_number           VARCHAR(64),
    notes                    TEXT,
    submitted_by             INT,             -- Users.user_id ของผู้จัดการที่กดส่งรายงาน
    reconciled_by            INT,             -- Users.user_id ของแอดมินที่ตรวจสอบกระทบยอด
    submitted_at             TEXT,
    reconciled_at            TEXT,
    paid_at                  TEXT,
    UNIQUE KEY uniq_center_period (center_id, period_month),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id),
    FOREIGN KEY (submitted_by) REFERENCES Users(user_id),
    FOREIGN KEY (reconciled_by) REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
