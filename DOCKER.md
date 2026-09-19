# รัน TD ServicePro ด้วย Docker

ระบบนี้เป็น Python (wsgiref + Jinja2) ต่อฐานข้อมูล **PostgreSQL** ผ่าน psycopg2
`docker-compose.yml` ที่แนบมาให้มี 2 service: `postgres` (ฐานข้อมูล) และ
`tdprinter-care` (ตัวแอป — ชื่อ service ในไฟล์ compose ยังใช้ tdprinter-care ตามเดิมเพื่อไม่ให้กระทบ container/volume ที่มีอยู่แล้ว) — รัน `docker compose up` ครั้งเดียวได้ทั้งคู่

> **ย้ายมาจาก MySQL อยู่หรือเปล่า?** ถ้า deploy นี้เคยใช้ MySQL มาก่อนและมีข้อมูลลูกค้า/ตั๋วซ่อมจริง
> ค้างอยู่ **ห้ามรัน `docker compose up` กับไฟล์นี้ตรงๆ ทันที** — ต้องทำตามขั้นตอนย้ายข้อมูลก่อน
> ดู [`MIGRATION.md`](MIGRATION.md) สำหรับขั้นตอนละเอียดทั้งหมด (สำรองข้อมูล, ตั้งฐานข้อมูลใหม่คู่ขนาน,
> รันสคริปต์ย้ายข้อมูล, ตรวจสอบก่อนตัดเข้าใช้งานจริง)

## วิธีที่ 1 — clone แล้ว compose up (แนะนำ สำหรับติดตั้งใหม่ที่ยังไม่มีข้อมูลเดิม)

```bash
git clone git@github.com:montri2025-sudo/TDPrinterCare.git
cd TDPrinterCare
docker compose up -d --build
```

แอปจะรอจน PostgreSQL พร้อม (มี healthcheck + retry loop ในตัว) แล้วค่อยสร้างตาราง/seed
ข้อมูลตัวอย่างให้เอง

**เพื่อความปลอดภัย ไฟล์ `docker-compose.yml` นี้ไม่ได้เปิดพอร์ต 8000 ออกสู่เครื่อง
host โดยตรง (ไม่มี `ports: "8000:8000"`)** — เข้าถึงแอปได้ทางเดียวคือผ่าน reverse
proxy บน `odoo-network` (ตาม `VIRTUAL_HOST=servicepro.tdprinter.com` /
`VIRTUAL_PORT=8000` ที่ตั้งไว้ในไฟล์) ดังนั้นต้องมี reverse proxy เช่น
nginx-proxy + acme-companion รันอยู่บน network นี้ก่อนถึงจะเข้าเว็บได้จริง ถ้า
อยากทดสอบเข้าตรงๆ ชั่วคราวโดยไม่ผ่าน proxy ให้ใช้
`docker compose exec tdprinter-care sh` เพื่อเข้าไป debug ข้างในแทน หรือเปิด
port-forward ชั่วคราวด้วย `docker compose port tdprinter-care 8000` — อย่าเปิด
`ports:` กลับมาถาวรบนเครื่อง production

**หมายเหตุเรื่อง network:** `docker-compose.yml` ต่อ container `tdprinter-care`
(ตัวแอป) เข้ากับ external network ชื่อ `odoo-network` ด้วย (สำหรับ reverse
proxy/Odoo ที่ต้องอยู่บน network นั้นเสมอ ไม่งั้นแอปจะเข้าถึงไม่ได้เลย) — network
นี้ **ต้องถูกสร้างไว้ก่อน** ไม่งั้น `docker compose up` จะ error ว่าหา network
ไม่เจอ สร้างครั้งเดียวด้วย:
```bash
docker network create odoo-network
```

## วิธีที่ 2 — build image ของแอปตรงจาก GitHub (ไม่ต้อง clone เอง)

Docker รองรับ git URL เป็น build context ได้เลย (ต้องมี SSH key เข้าถึง repo
หรือใช้ URL แบบ HTTPS ถ้า repo เป็น public):

```bash
docker build -t tdprinter-care git@github.com:montri2025-sudo/TDPrinterCare.git
```

วิธีนี้ได้แค่ image ของแอป — ยังต้องรัน PostgreSQL แยกเอง (ดูตัวแปรแวดล้อมด้านล่าง
เพื่อชี้แอปไปหา PostgreSQL instance ของคุณ) แนะนำใช้วิธีที่ 1 กับ docker-compose แทน
เพราะจัดการทั้งคู่ให้พร้อมกัน

## รันด้วย docker run ตรง ๆ (ไม่ใช้ compose — ต้องมี PostgreSQL รันอยู่แล้วนอก Docker หรือคนละ container)

```bash
docker build -t tdprinter-care .
mkdir -p uploads
docker run -d --name tdprinter-care \
  -p 8000:8000 \
  -e PG_HOST=<host ของ PostgreSQL> \
  -e PG_PORT=5432 \
  -e PG_USER=tdprinter \
  -e PG_PASSWORD=<รหัสผ่านจริงของคุณ> \
  -e PG_DATABASE=tdprinter_care \
  -e SEED_DEMO_DATA=0 \
  -v "$(pwd)/uploads:/app/uploads" \
  --restart unless-stopped \
  tdprinter-care
```

## การเก็บข้อมูลถาวร (Persistence)

- ฐานข้อมูล PostgreSQL → เก็บไว้ที่โฟลเดอร์ `./postgres-data` บนเครื่อง host (mount เข้า
  `/var/lib/postgresql/data` ของ container `postgres`)
- รูปภาพ/วิดีโอที่อัปโหลด → เก็บไว้ที่โฟลเดอร์ `./uploads` บนเครื่อง host

หากลบ container แล้วสร้างใหม่ ข้อมูลจะยังอยู่ครบตราบใดที่โฟลเดอร์ทั้งสองยังอยู่

**ก่อนใช้งานจริง ต้องตั้งค่าไฟล์ `.env` ก่อนเสมอ** (ดูหัวข้อถัดไป) — ถ้าไม่ตั้งค่า
`PG_PASSWORD` ใน `.env` ไฟล์ `docker-compose.yml` จะปฏิเสธ
การรันทันที (กันไม่ให้เผลอ deploy ด้วยรหัสผ่านตัวอย่าง)

```bash
cp .env.example .env
# แก้ .env ให้ครบ: ตั้งรหัสผ่าน PostgreSQL ใหม่, ตั้ง SEED_DEMO_DATA=0,
# ตั้ง INITIAL_ADMIN_USERNAME/PASSWORD เป็นบัญชีแอดมินจริงของร้าน
docker compose up -d --build
```

## ตัวแปรแวดล้อม (Environment variables)

ตั้งค่าทั้งหมดนี้ผ่านไฟล์ `.env` (ก็อปจาก `.env.example`) — **ห้าม commit ไฟล์ .env
เข้า git** (มีอยู่ใน `.gitignore` ให้แล้ว)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `PORT` | `8000` | พอร์ตที่ web server ฟัง |
| `PG_HOST` | `127.0.0.1` | โฮสต์ของ PostgreSQL (ใน compose คือชื่อ service `postgres`) |
| `PG_PORT` | `5432` | พอร์ตของ PostgreSQL |
| `PG_USER` | `tdprinter` | ผู้ใช้ฐานข้อมูล |
| `PG_PASSWORD` | *(ต้องตั้งเอง)* | รหัสผ่านฐานข้อมูล — ตั้งใหม่ใน `.env` เสมอ |
| `PG_DATABASE` | `tdprinter_care` | ชื่อฐานข้อมูล (ระบบจะสร้างให้อัตโนมัติถ้ายังไม่มี) |
| `SEED_DEMO_DATA` | `1` | `0` = ไม่ใส่ข้อมูลตัวอย่าง/บัญชีทดสอบ (แนะนำสำหรับใช้งานจริง) |
| `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` | *(ไม่ตั้ง)* | ถ้าตั้งไว้และ `SEED_DEMO_DATA=0` + ฐานข้อมูลว่าง ระบบจะสร้างบัญชีแอดมินคนแรกจากค่านี้ให้อัตโนมัติ |
| `COOKIE_SECURE` | `1` | session cookie จะส่งเฉพาะผ่าน HTTPS — ตั้งเป็น `0` เฉพาะตอนทดสอบผ่าน http ธรรมดาบนเครื่อง dev เท่านั้น |
| `ODOO_URL` | `http://odoo:8069` | ที่อยู่ของ Odoo (ค่าเริ่มต้นชี้เข้า container `odoo` ในไฟล์นี้โดยตรง) |
| `ODOO_DB` | *(ไม่ตั้ง = ข้ามการซิงก์)* | ชื่อฐานข้อมูล Odoo ที่จะซิงก์เข้า |
| `ODOO_USERNAME` | *(ไม่ตั้ง = ข้ามการซิงก์)* | อีเมล/ชื่อผู้ใช้ Odoo ที่ใช้ยืนยันตัวตนตอนซิงก์ |
| `ODOO_API_KEY` | *(ไม่ตั้ง = ข้ามการซิงก์)* | API key ของผู้ใช้ Odoo ด้านบน (ดูวิธีสร้างในหัวข้อ "เชื่อมต่อ Odoo" ด้านล่าง) |
| `ODOO_MASTER_PASSWORD` | *(ต้องตั้งเอง ถ้าใช้ service odoo)* | Master Password ของหน้า Database Manager Odoo — ตั้งไว้ตายตัว ไม่ต้องเข้าเว็บตั้งเองรอบแรก (ดูหัวข้อ "เชื่อมต่อ Odoo") |

## เชื่อมต่อ Odoo (ไม่บังคับ)

ฟีเจอร์นี้ซิงก์ข้อมูล 4 ประเภทจากระบบนี้ไป Odoo แบบอัตโนมัติทันทีทุกครั้งที่สร้าง/แก้ไขข้อมูล —
ถ้าไม่ตั้งค่าอะไรเลย ระบบจะทำงานปกติทุกอย่างเหมือนเดิม (ฟีเจอร์นี้แค่ข้ามไปเงียบๆ):

| ข้อมูลในระบบนี้ | ไปเป็นอะไรใน Odoo | หมายเหตุ |
|---|---|---|
| ลูกค้า (Customers) | `res.partner` (customer_rank=1) | ชื่อ/เบอร์/อีเมล/ที่อยู่/เลขผู้เสียภาษี |
| สินค้า/อะไหล่ (Spare_Parts) | `product.template` | ประเภทสินค้า (FDM/Resin/อะไหล่/วัสดุพิมพ์/อื่นๆ) จะถูกสร้างเป็นหมวดหมู่สินค้า (`product.category`) ให้อัตโนมัติด้วย |
| พนักงาน/ทีมงานภายใน (Users, ไม่รวมบัญชีลูกค้า) | `res.users` | ดูหมายเหตุสำคัญด้านล่าง — ต้องตั้งรหัสผ่าน/สิทธิ์เพิ่มเติมเองในฝั่ง Odoo |
| ศูนย์บริการพาร์ทเนอร์ (Service_Centers) | `res.partner` (is_company=1, แยกจากลูกค้า) | ชื่อ/ที่อยู่/เบอร์/เลขผู้เสียภาษี/อีเมล/เว็บไซต์ |

**ข้อมูลเดิมที่มีอยู่ก่อนเปิดใช้ฟีเจอร์นี้จะยังไม่ถูกซิงก์อัตโนมัติ** (การซิงก์อัตโนมัติทำงานเฉพาะตอน
สร้าง/แก้ไขข้อมูล**ใหม่**เท่านั้น) — นำเข้าข้อมูลเดิมทั้งหมดครั้งเดียวได้ที่หน้า **แอดมิน → 🔗 ซิงก์ข้อมูล
ไป Odoo** (`/admin/odoo-sync`) เลือกประเภทที่ต้องการแล้วกดซิงก์ได้เลย ปลอดภัย กดซ้ำได้ทุกเมื่อ (ใช้
กลไกจับคู่ข้อมูลเดิม ไม่สร้างข้อมูลซ้ำใน Odoo)

**หมายเหตุสำคัญเรื่องพนักงาน (res.users):** ระบบนี้ไม่มีช่องอีเมลของพนักงาน (มีแค่ username/phone)
บัญชีที่ซิงก์เข้าไปใหม่จึงยัง **ไม่มีรหัสผ่าน** และได้สิทธิ์เริ่มต้นแค่ "Internal User" (เข้า Odoo ได้
แต่ไม่มีสิทธิ์พิเศษ) เท่านั้น — หลังซิงก์แล้วต้องเข้าไปที่ Odoo Settings → Users เพื่อ (1) ตั้งรหัสผ่าน
หรือกด "Send Invitation Email" ให้แต่ละคน และ (2) ปรับสิทธิ์การเข้าถึงเพิ่มเติมให้ตรงกับหน้าที่จริงของ
แต่ละคน (เช่น เซล/ช่าง/ผู้จัดการ) เอง — ฟีเจอร์นี้ไม่ได้เดาสิทธิ์เหล่านี้ให้อัตโนมัติเพื่อความปลอดภัย

`docker-compose.yml` มี service `odoo` (ตัวแอป Odoo) และ `odoo-db` (ฐานข้อมูลของ Odoo เอง
แยกจากฐานข้อมูลของ TD ServicePro) แนบมาให้พร้อมใช้งานแล้ว — ถ้ายังไม่เคยติดตั้ง Odoo มาก่อน
ทำตามขั้นตอนนี้:

**1) ตั้งรหัสผ่านฐานข้อมูล Odoo + Master Password แล้วเปิด container**

ใน `.env` ตั้งค่า `ODOO_DB_PASSWORD` เป็นรหัสผ่านสุ่มยาวๆ (คนละค่ากับ `PG_PASSWORD`) และตั้งค่า
`ODOO_MASTER_PASSWORD` เป็นรหัสผ่านที่ต้องการใช้เป็น Master Password ของ Odoo (ค่าเริ่มต้นใน
`.env.example` คือ `Tong@1234` — เปลี่ยนได้ตามต้องการ) **service `odoo` build จาก Dockerfile ของ
เราเอง (ไม่ใช่ pull image ทางการตรงๆ) ต้องใช้ `--build` ตอนเปิดครั้งแรก:**

```bash
docker compose up -d --build odoo-db odoo
```

รอสัก 1-2 นาทีให้ Odoo เริ่มระบบครั้งแรกเสร็จ (เช็กได้ด้วย `docker compose logs -f odoo`) —
ระบบจะเขียนค่า `ODOO_MASTER_PASSWORD` เข้า odoo.conf ให้อัตโนมัติทุกครั้งที่ container เริ่มทำงาน
(ดู `odoo/entrypoint-wrapper.sh`) จึงไม่ต้องเข้าเว็บไปตั้ง Master Password เองแบบ Odoo เปล่าๆ —
**ข้อดีคือย้าย deploy ไปเซิร์ฟเวอร์ใหม่เมื่อไหร่ก็ได้ Master Password เดิมทันที** แค่พก `.env`
(หรือตั้งค่า `ODOO_MASTER_PASSWORD` เดียวกัน) ไปด้วยเท่านั้น

**2) สร้างฐานข้อมูล Odoo ครั้งแรกผ่านหน้าเว็บ**

เข้าหน้าเว็บ Odoo ได้ 2 ทาง:
- ถ้าตั้ง `ODOO_VIRTUAL_HOST` ไว้และมี reverse proxy จัดการโดเมนย่อยนั้นอยู่แล้ว → เข้าผ่านโดเมนนั้นได้เลย
- ถ้ายังไม่มี ใช้ SSH tunnel ชั่วคราวจากเครื่องตัวเองมาที่เซิร์ฟเวอร์แทน:
  ```bash
  ssh -L 8069:localhost:8069 <user>@<เซิร์ฟเวอร์ของคุณ>
  ```
  แล้วเปิดเบราว์เซอร์ไปที่ `http://localhost:8069`

หน้าแรกจะให้กรอก **Master Password** (ใส่ค่าเดียวกับ `ODOO_MASTER_PASSWORD` ใน `.env` — ระบบตั้ง
ไว้ให้แล้วตั้งแต่ container เริ่มทำงาน คนละตัวกับรหัสผ่าน login ผู้ใช้), ชื่อฐานข้อมูล (จำค่านี้ไว้
ใส่ `ODOO_DB`), อีเมล/รหัสผ่านผู้ดูแลระบบ Odoo คนแรก (จำอีเมลไว้ใส่ `ODOO_USERNAME`), ภาษา,
ประเทศ — ปิดตัวเลือก "Demo data" ถ้าไม่ต้องการข้อมูลตัวอย่างของ Odoo เอง แล้วกด Create database

**3) สร้าง API Key สำหรับซิงก์ข้อมูล**

ล็อกอินเข้า Odoo ด้วยบัญชีที่เพิ่งสร้าง แล้ว:
1. เปิด developer mode: ไปที่ Settings → เลื่อนลงล่างสุด → "Activate the developer mode"
2. ไปที่ Settings → Users & Companies → Users → เลือกผู้ใช้ที่จะใช้ซิงก์ (จะใช้บัญชีแอดมินที่
   เพิ่งสร้างก็ได้) → แท็บ "Account Security" → ปุ่ม "New API Key"
3. ตั้งชื่อคีย์ (เช่น "TD ServicePro sync") แล้วกดยืนยัน — ระบบจะโชว์คีย์ให้ครั้งเดียวเท่านั้น
   คัดลอกเก็บไว้ทันที

**4) ตั้งค่าใน `.env` แล้วรีสตาร์ทแอป**

```bash
ODOO_DB=<ชื่อฐานข้อมูลจากข้อ 2>
ODOO_USERNAME=<อีเมลผู้ใช้จากข้อ 2>
ODOO_API_KEY=<API key จากข้อ 3>
```

แล้วรัน (ต้องใช้ `--build` ไม่ใช่แค่ `restart` เพื่อให้ค่า env ใหม่ถูกอ่านเข้าไป):

```bash
docker compose up -d --build tdprinter-care
```

จากนี้ทุกครั้งที่สร้างหรือแก้ไขข้อมูลลูกค้าในระบบ (ทั้งจากแอดมิน/ผู้จัดการ/เซล หรือลูกค้าสมัครเอง)
จะซิงก์เข้า Odoo ให้อัตโนมัติ — ถ้าซิงก์ไม่สำเร็จ (Odoo ปิดอยู่/ตั้งค่าผิด) จะไม่กระทบการสร้าง/แก้ไข
ลูกค้าในระบบหลักเลย แค่ log ข้อความไว้ใน `docker compose logs tdprinter-care` เท่านั้น
ตรวจสอบได้ด้วยคำสั่ง:

```bash
docker compose logs tdprinter-care | grep odoo_client
```

## หมายเหตุสำหรับการใช้งานจริง (production)

**เช็กลิสต์ก่อน deploy จริง:**

1. ตั้งรหัสผ่าน PostgreSQL ใหม่ทั้งหมดใน `.env` (ห้ามใช้ค่าตัวอย่าง)
2. ตั้ง `SEED_DEMO_DATA=0` และตั้ง `INITIAL_ADMIN_USERNAME`/`INITIAL_ADMIN_PASSWORD`
   เป็นบัญชีแอดมินจริง (หรือถ้าเผลอ seed ไปแล้ว ให้ลบ/เปลี่ยนรหัสผ่านบัญชีทดสอบ
   admin1/tech1/tech2/mgr1/sale1/cust1/cust2 ทั้งหมดทันทีหลัง login ครั้งแรก)
   — **ถ้ากำลังย้ายข้อมูลจริงจาก MySQL เดิม ไม่ต้องตั้งค่าสองตัวนี้ ให้ทำตาม MIGRATION.md แทน**
3. วาง reverse proxy ที่ทำ TLS/HTTPS ไว้หน้าแอปเสมอ (เช่น nginx-proxy +
   acme-companion, Caddy, Cloudflare Tunnel) แล้วปล่อยให้ `COOKIE_SECURE=1`
   (ค่าเริ่มต้น) ไว้ — ถ้ายังไม่มี HTTPS ห้าม deploy ระบบจริงที่มีข้อมูลลูกค้า
4. สำรองข้อมูล (backup) โฟลเดอร์ `./postgres-data` หรือใช้ `pg_dump` เป็นประจำ เช่น
   `docker exec tdprinter-postgres pg_dump -U tdprinter tdprinter_care > backup.sql`

**สถานะความปลอดภัยของระบบล็อกอิน (อัปเดตล่าสุด):**

- รหัสผ่านเข้ารหัสด้วย PBKDF2-HMAC-SHA256 + salt สุ่มต่อผู้ใช้ (260,000 รอบ) —
  บัญชีเก่าที่เคย hash แบบ SHA-256 เปล่าๆ จะถูกอัปเกรดให้อัตโนมัติทันทีที่ login สำเร็จครั้งถัดไป
- Session หมดอายุอัตโนมัติ (ไม่ใช้งาน 8 ชม. หรือครบ 24 ชม. ไม่ว่ากรณีใด) และเก็บใน
  หน่วยความจำของ process แอป (restart container ของแอปแล้วทุกคนต้อง login ใหม่ —
  แต่ข้อมูลใน PostgreSQL จะไม่หาย)
- มีการป้องกัน CSRF (ทุกฟอร์มที่ล็อกอินแล้วต้องแนบ token ที่ตรงกับ session) และ
  จำกัดจำนวนครั้งที่ login ผิดพลาด (ล็อกชั่วคราว 15 นาทีหลังผิด 5 ครั้งต่อคู่ IP+username)
- server ที่รันอยู่ (`wsgiref` + ThreadingMixIn ที่เพิ่มเข้ามา) รองรับ concurrent
  request ได้ในระดับหนึ่งด้วย stdlib ล้วน แต่ยังไม่ทนทานเท่า production WSGI server
  จริงจัง (เช่น gunicorn/uwsgi) — สำหรับร้านขนาดเล็ก/กลางใช้ได้ แต่ถ้าคาดว่าจะมี
  ผู้ใช้พร้อมกันจำนวนมาก ควรพิจารณาย้ายไป gunicorn ในอนาคต
- ใช้ PostgreSQL จึงรัน `tdprinter-care` แอปได้หลาย instance พร้อมกัน (scale
  แนวนอน) โดยไม่มีปัญหาเรื่องฐานข้อมูล — แต่ session/CSRF token/ตัวนับ login ที่ผิด
  ยังเก็บในหน่วยความจำต่อ instance อยู่ ถ้า scale หลาย instance จริงควรย้ายไปเก็บใน
  Redis เพื่อให้ผู้ใช้ล็อกอินค้างได้ไม่ว่าจะตกไปที่ instance ไหน
