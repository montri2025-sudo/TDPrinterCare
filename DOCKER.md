# รัน TD ServicePro ด้วย Docker

ระบบนี้เป็น Python (wsgiref + Jinja2) ต่อฐานข้อมูล **MySQL** ผ่าน PyMySQL
`docker-compose.yml` ที่แนบมาให้มี 2 service: `mysql` (ฐานข้อมูล) และ
`tdprinter-care` (ตัวแอป — ชื่อ service ในไฟล์ compose ยังใช้ tdprinter-care ตามเดิมเพื่อไม่ให้กระทบ container/volume ที่มีอยู่แล้ว) — รัน `docker compose up` ครั้งเดียวได้ทั้งคู่

## วิธีที่ 1 — clone แล้ว compose up (แนะนำ)

```bash
git clone git@github.com:montri2025-sudo/TDPrinterCare.git
cd TDPrinterCare
docker compose up -d --build
```

แอปจะรอจน MySQL พร้อม (มี healthcheck + retry loop ในตัว) แล้วค่อยสร้างตาราง/seed
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

วิธีนี้ได้แค่ image ของแอป — ยังต้องรัน MySQL แยกเอง (ดูตัวแปรแวดล้อมด้านล่าง
เพื่อชี้แอปไปหา MySQL instance ของคุณ) แนะนำใช้วิธีที่ 1 กับ docker-compose แทน
เพราะจัดการทั้งคู่ให้พร้อมกัน

## รันด้วย docker run ตรง ๆ (ไม่ใช้ compose — ต้องมี MySQL รันอยู่แล้วนอก Docker หรือคนละ container)

```bash
docker build -t tdprinter-care .
mkdir -p uploads
docker run -d --name tdprinter-care \
  -p 8000:8000 \
  -e MYSQL_HOST=<host ของ MySQL> \
  -e MYSQL_PORT=3306 \
  -e MYSQL_USER=tdprinter \
  -e MYSQL_PASSWORD=<รหัสผ่านจริงของคุณ> \
  -e MYSQL_DATABASE=tdprinter_care \
  -e SEED_DEMO_DATA=0 \
  -v "$(pwd)/uploads:/app/uploads" \
  --restart unless-stopped \
  tdprinter-care
```

## การเก็บข้อมูลถาวร (Persistence)

- ฐานข้อมูล MySQL → เก็บไว้ที่โฟลเดอร์ `./mysql-data` บนเครื่อง host (mount เข้า
  `/var/lib/mysql` ของ container `mysql`)
- รูปภาพ/วิดีโอที่อัปโหลด → เก็บไว้ที่โฟลเดอร์ `./uploads` บนเครื่อง host

หากลบ container แล้วสร้างใหม่ ข้อมูลจะยังอยู่ครบตราบใดที่โฟลเดอร์ทั้งสองยังอยู่

**ก่อนใช้งานจริง ต้องตั้งค่าไฟล์ `.env` ก่อนเสมอ** (ดูหัวข้อถัดไป) — ถ้าไม่ตั้งค่า
`MYSQL_ROOT_PASSWORD`/`MYSQL_PASSWORD` ใน `.env` ไฟล์ `docker-compose.yml` จะปฏิเสธ
การรันทันที (กันไม่ให้เผลอ deploy ด้วยรหัสผ่านตัวอย่าง)

```bash
cp .env.example .env
# แก้ .env ให้ครบ: ตั้งรหัสผ่าน MySQL ใหม่, ตั้ง SEED_DEMO_DATA=0,
# ตั้ง INITIAL_ADMIN_USERNAME/PASSWORD เป็นบัญชีแอดมินจริงของร้าน
docker compose up -d --build
```

## ตัวแปรแวดล้อม (Environment variables)

ตั้งค่าทั้งหมดนี้ผ่านไฟล์ `.env` (ก็อปจาก `.env.example`) — **ห้าม commit ไฟล์ .env
เข้า git** (มีอยู่ใน `.gitignore` ให้แล้ว)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `PORT` | `8000` | พอร์ตที่ web server ฟัง |
| `MYSQL_HOST` | `127.0.0.1` | โฮสต์ของ MySQL (ใน compose คือชื่อ service `mysql`) |
| `MYSQL_PORT` | `3306` | พอร์ตของ MySQL |
| `MYSQL_USER` | `tdprinter` | ผู้ใช้ฐานข้อมูล |
| `MYSQL_PASSWORD` | *(ต้องตั้งเอง)* | รหัสผ่านฐานข้อมูล — ตั้งใหม่ใน `.env` เสมอ |
| `MYSQL_ROOT_PASSWORD` | *(ต้องตั้งเอง)* | รหัสผ่าน root ของ MySQL — ตั้งใหม่ใน `.env` เสมอ |
| `MYSQL_DATABASE` | `tdprinter_care` | ชื่อฐานข้อมูล (ระบบจะสร้างให้อัตโนมัติถ้ายังไม่มี) |
| `SEED_DEMO_DATA` | `1` | `0` = ไม่ใส่ข้อมูลตัวอย่าง/บัญชีทดสอบ (แนะนำสำหรับใช้งานจริง) |
| `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` | *(ไม่ตั้ง)* | ถ้าตั้งไว้และ `SEED_DEMO_DATA=0` + ฐานข้อมูลว่าง ระบบจะสร้างบัญชีแอดมินคนแรกจากค่านี้ให้อัตโนมัติ |
| `COOKIE_SECURE` | `1` | session cookie จะส่งเฉพาะผ่าน HTTPS — ตั้งเป็น `0` เฉพาะตอนทดสอบผ่าน http ธรรมดาบนเครื่อง dev เท่านั้น |

## หมายเหตุสำหรับการใช้งานจริง (production)

**เช็กลิสต์ก่อน deploy จริง:**

1. ตั้งรหัสผ่าน MySQL ใหม่ทั้งหมดใน `.env` (ห้ามใช้ค่าตัวอย่าง)
2. ตั้ง `SEED_DEMO_DATA=0` และตั้ง `INITIAL_ADMIN_USERNAME`/`INITIAL_ADMIN_PASSWORD`
   เป็นบัญชีแอดมินจริง (หรือถ้าเผลอ seed ไปแล้ว ให้ลบ/เปลี่ยนรหัสผ่านบัญชีทดสอบ
   admin1/tech1/tech2/mgr1/sale1/cust1/cust2 ทั้งหมดทันทีหลัง login ครั้งแรก)
3. วาง reverse proxy ที่ทำ TLS/HTTPS ไว้หน้าแอปเสมอ (เช่น nginx-proxy +
   acme-companion, Caddy, Cloudflare Tunnel) แล้วปล่อยให้ `COOKIE_SECURE=1`
   (ค่าเริ่มต้น) ไว้ — ถ้ายังไม่มี HTTPS ห้าม deploy ระบบจริงที่มีข้อมูลลูกค้า
4. สำรองข้อมูล (backup) โฟลเดอร์ `./mysql-data` หรือใช้ `mysqldump` เป็นประจำ

**สถานะความปลอดภัยของระบบล็อกอิน (อัปเดตล่าสุด):**

- รหัสผ่านเข้ารหัสด้วย PBKDF2-HMAC-SHA256 + salt สุ่มต่อผู้ใช้ (260,000 รอบ) —
  บัญชีเก่าที่เคย hash แบบ SHA-256 เปล่าๆ จะถูกอัปเกรดให้อัตโนมัติทันทีที่ login สำเร็จครั้งถัดไป
- Session หมดอายุอัตโนมัติ (ไม่ใช้งาน 8 ชม. หรือครบ 24 ชม. ไม่ว่ากรณีใด) และเก็บใน
  หน่วยความจำของ process แอป (restart container ของแอปแล้วทุกคนต้อง login ใหม่ —
  แต่ข้อมูลใน MySQL จะไม่หาย)
- มีการป้องกัน CSRF (ทุกฟอร์มที่ล็อกอินแล้วต้องแนบ token ที่ตรงกับ session) และ
  จำกัดจำนวนครั้งที่ login ผิดพลาด (ล็อกชั่วคราว 15 นาทีหลังผิด 5 ครั้งต่อคู่ IP+username)
- server ที่รันอยู่ (`wsgiref` + ThreadingMixIn ที่เพิ่มเข้ามา) รองรับ concurrent
  request ได้ในระดับหนึ่งด้วย stdlib ล้วน แต่ยังไม่ทนทานเท่า production WSGI server
  จริงจัง (เช่น gunicorn/uwsgi) — สำหรับร้านขนาดเล็ก/กลางใช้ได้ แต่ถ้าคาดว่าจะมี
  ผู้ใช้พร้อมกันจำนวนมาก ควรพิจารณาย้ายไป gunicorn ในอนาคต
- ตอนนี้ใช้ MySQL แล้ว จึงรัน `tdprinter-care` แอปได้หลาย instance พร้อมกัน (scale
  แนวนอน) โดยไม่มีปัญหาเรื่องฐานข้อมูล — แต่ session/CSRF token/ตัวนับ login ที่ผิด
  ยังเก็บในหน่วยความจำต่อ instance อยู่ ถ้า scale หลาย instance จริงควรย้ายไปเก็บใน
  Redis เพื่อให้ผู้ใช้ล็อกอินค้างได้ไม่ว่าจะตกไปที่ instance ไหน
