-- ระบบบริหารจัดการงานซ่อม (Repair Ticketing System) — SQLite schema

CREATE TABLE IF NOT EXISTS Service_Centers (
    center_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    address     TEXT,
    phone       TEXT,
    latitude    REAL,   -- พิกัดสำหรับปักหมุดบนแผนที่ (ไม่บังคับ)
    longitude   REAL
);

CREATE TABLE IF NOT EXISTS Users (
    user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT UNIQUE NOT NULL,
    password     TEXT NOT NULL,               -- sha256 hash (demo only)
    role         TEXT NOT NULL CHECK (role IN ('customer','admin','technician','manager')),
    name         TEXT NOT NULL,
    customer_id  INTEGER,                     -- only set when role = 'customer'
    center_id    INTEGER,                     -- ศูนย์บริการที่ผู้ใช้งานสังกัด (สำหรับ staff)
    is_active    INTEGER NOT NULL DEFAULT 1,  -- 0 = ระงับการใช้งาน (soft delete)
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id)
);

CREATE TABLE IF NOT EXISTS Customers (
    customer_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    phone        TEXT,
    email        TEXT,
    line_id      TEXT,
    address      TEXT
);

CREATE TABLE IF NOT EXISTS Devices (
    device_sn         TEXT PRIMARY KEY,
    customer_id       INTEGER NOT NULL,
    model             TEXT NOT NULL,
    type              TEXT CHECK (type IN ('FDM','Resin')),
    purchase_date     TEXT,
    warranty_end_date TEXT,
    FOREIGN KEY (customer_id) REFERENCES Customers(customer_id)
);

CREATE TABLE IF NOT EXISTS Tickets (
    ticket_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    device_sn        TEXT NOT NULL,
    issue_category   TEXT,
    description      TEXT,
    center_id        INTEGER,                -- สาขาที่ลูกค้าเลือกเข้ารับบริการ
    status           TEXT NOT NULL DEFAULT 'New'
                     CHECK (status IN ('New','Diagnosing','Waiting for Parts','In Repair','Testing','Resolved/Closed')),
    assigned_tech_id INTEGER,
    created_at       TEXT NOT NULL,
    closed_at        TEXT,
    csat_score       INTEGER,
    csat_comment     TEXT,
    FOREIGN KEY (device_sn) REFERENCES Devices(device_sn),
    FOREIGN KEY (assigned_tech_id) REFERENCES Users(user_id),
    FOREIGN KEY (center_id) REFERENCES Service_Centers(center_id)
);

CREATE TABLE IF NOT EXISTS Ticket_Media (
    media_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id     INTEGER NOT NULL,
    media_type    TEXT NOT NULL CHECK (media_type IN ('image','video')),
    filename      TEXT NOT NULL,      -- ชื่อไฟล์เดิมจากลูกค้า
    stored_name   TEXT NOT NULL,      -- ชื่อไฟล์ที่เก็บจริงในดิสก์ (กันชื่อชนกัน/อันตราย)
    uploaded_at   TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id)
);

CREATE TABLE IF NOT EXISTS Spare_Parts (
    part_sku           TEXT PRIMARY KEY,
    part_name          TEXT NOT NULL,
    compatible_models  TEXT,
    stock_quantity     INTEGER NOT NULL DEFAULT 0,
    cost_price         REAL NOT NULL DEFAULT 0,
    labor_fee          REAL NOT NULL DEFAULT 0,  -- ค่าบริการเปลี่ยนอุปกรณ์มาตรฐานของอะไหล่ชิ้นนี้
    reorder_level      INTEGER NOT NULL DEFAULT 0,
    image_filename     TEXT                       -- ชื่อไฟล์รูปอะไหล่ (1 รูปต่อชิ้น) เก็บจริงใน uploads/parts/
);

CREATE TABLE IF NOT EXISTS Service_Logs (
    log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id        INTEGER NOT NULL,
    part_sku_used    TEXT,
    quantity_used    INTEGER DEFAULT 0,
    action_taken     TEXT,
    tech_notes       TEXT,
    labor_fee        REAL NOT NULL DEFAULT 0,       -- ค่าบริการเปลี่ยนอุปกรณ์ที่เรียกเก็บจริง (ช่างปรับได้ต่องาน)
    approval_status  TEXT NOT NULL DEFAULT 'auto'   -- auto | pending | approved | rejected
                     CHECK (approval_status IN ('auto','pending','approved','rejected')),
    created_at       TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (part_sku_used) REFERENCES Spare_Parts(part_sku)
);

CREATE TABLE IF NOT EXISTS Quotations (
    quote_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER NOT NULL,
    created_by   INTEGER NOT NULL,   -- Users.user_id ของช่างที่ออกใบเสนอราคา
    created_at   TEXT NOT NULL,
    notes        TEXT,
    FOREIGN KEY (ticket_id) REFERENCES Tickets(ticket_id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS Quotation_Items (
    item_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id     INTEGER NOT NULL,
    description  TEXT NOT NULL,
    quantity     REAL NOT NULL DEFAULT 1,
    unit_price   REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (quote_id) REFERENCES Quotations(quote_id)
);
