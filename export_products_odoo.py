#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_products_odoo.py — ส่งออกข้อมูลสินค้า/อะไหล่ทั้งหมด (ตาราง Spare_Parts + Part_Images) ให้พร้อม
นำเข้า Odoo (product.template) ด้วยตัวเองผ่านหน้า Inventory/Sales > Products > Import

วิธีใช้ (รันบนเครื่อง/คอนเทนเนอร์ที่ต่อฐานข้อมูลจริงได้ เช่นเดียวกับที่รัน app.py):
    python3 export_products_odoo.py [--out-dir ./odoo_export]

ถ้ารันผ่าน Docker Compose (service ชื่อ app หรือ web ตาม docker-compose.yml ของโปรเจกต์นี้):
    docker compose exec app python3 export_products_odoo.py --out-dir /app/odoo_export
    (จากนั้น docker compose cp app:/app/odoo_export ./odoo_export ก็อปออกมาเครื่องตัวเอง)

สคริปต์นี้ใช้ตัวแปรแวดล้อมเดียวกับ app.py ทุกประการ (PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE)
ผ่านโมดูล db.py ที่มีอยู่แล้วในโปรเจกต์ — ไม่ต้องตั้งค่าเพิ่ม ถ้า docker-compose.yml ตั้งไว้ถูกต้องอยู่แล้ว

ผลลัพธ์ที่ได้ในโฟลเดอร์ --out-dir:
    products_odoo_import.csv   — ไฟล์ CSV พร้อมนำเข้า Odoo (มีคอลัมน์ "Image 1920" เป็นรูปปก
                                  เข้ารหัส base64 ฝังมาในไฟล์เลย นำเข้าทีเดียวได้ครบทั้งข้อมูลและรูป)
    images/<SKU>/               — โฟลเดอร์รูปจริงของสินค้าแต่ละชิ้น (รูปปก + รูปแกลเลอรีทั้งหมด)
                                  เผื่อกรณีอยากแนบรูปเพิ่มเติมเองทีหลัง หรือ CSV รูปใหญ่เกินนำเข้าทีเดียวไม่ไหว
    product_images.zip          — ไฟล์ zip ของโฟลเดอร์ images/ ทั้งหมด ดาวน์โหลดสะดวกไฟล์เดียว
    README_นำเข้า_Odoo.txt      — คำแนะนำขั้นตอนนำเข้าเป็นภาษาไทย
"""
import argparse
import base64
import csv
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  (ต้อง insert path ก่อนถึง import ได้ตอนรันจากที่อื่น)

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
PART_IMAGES_DIR = os.path.join(UPLOADS_DIR, "parts")

PRODUCT_CATEGORY_LABELS = {
    "FDM_Printer": "เครื่องพิมพ์ FDM",
    "Resin_Printer": "เครื่องพิมพ์ Resin",
    "Spare_Part": "อะไหล่",
    "Material": "วัสดุพิมพ์",
    "Other": "อื่นๆ",
}

CSV_HEADERS = [
    "Internal Reference",   # default_code — รหัส SKU ใช้จับคู่ตอน sync/import ซ้ำในอนาคตด้วย
    "Name",                 # name
    "Sales Price",          # list_price
    "Cost",                 # standard_price
    "Product Category",     # categ_id (พิมพ์เป็นชื่อหมวด — ตอน import Odoo จะถามว่าสร้างหมวดใหม่ไหมถ้ายังไม่มี)
    "Sales Description",    # description_sale
    "Image 1920",           # รูปปกหลัก เข้ารหัส base64 (เว้นว่างได้ถ้าไม่มีรูป)
    "สต็อกคงเหลือ (อ้างอิง)",  # ไม่ใช่ฟิลด์มาตรฐานของ Odoo — ใส่ไว้ให้ดูอ้างอิงเฉยๆ อย่าแมปตอน import
                              # (จำนวนคงคลังจริงต้องตั้งแยกหลังสินค้าเข้าระบบแล้ว ผ่าน Inventory > Update Quantity)
    "ตำแหน่งจัดเก็บ (อ้างอิง)",  # storage_location — ไม่ใช่ฟิลด์มาตรฐานของ Odoo เช่นกัน ใส่ไว้อ้างอิง
]


def safe_ext(filename):
    _, ext = os.path.splitext(filename or "")
    return ext or ".jpg"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="./odoo_export", help="โฟลเดอร์ปลายทางที่จะเขียนไฟล์ผลลัพธ์ทั้งหมด")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    images_out_dir = os.path.join(out_dir, "images")
    os.makedirs(images_out_dir, exist_ok=True)

    conn = db.get_conn()
    parts = conn.execute("SELECT * FROM Spare_Parts ORDER BY part_sku").fetchall()

    rows_written = 0
    images_copied = 0
    missing_image_files = []

    csv_path = os.path.join(out_dir, "products_odoo_import.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

        for p in parts:
            sku = p["part_sku"]
            part_dir = os.path.join(images_out_dir, sku)

            # --- รูปปกหลัก: เข้ารหัส base64 ฝังลง CSV + คัดลอกไฟล์จริงไว้ในโฟลเดอร์ images/<SKU>/ ด้วย ---
            image_b64 = ""
            if p["image_filename"]:
                src = os.path.join(PART_IMAGES_DIR, p["image_filename"])
                if os.path.isfile(src):
                    os.makedirs(part_dir, exist_ok=True)
                    with open(src, "rb") as img_f:
                        data = img_f.read()
                    image_b64 = base64.b64encode(data).decode("ascii")
                    cover_name = "cover" + safe_ext(p["image_filename"])
                    with open(os.path.join(part_dir, cover_name), "wb") as out_f:
                        out_f.write(data)
                    images_copied += 1
                else:
                    missing_image_files.append(src)

            # --- รูปแกลเลอรีเพิ่มเติม (ไม่ฝังลง CSV เพราะ Odoo product.template import รองรับรูปเดียวต่อแถว
            #     แต่คัดลอกไฟล์จริงไว้ให้ครบ เผื่อใครอยากแนบเพิ่มเองทีหลังผ่านแท็บ "รูปภาพอื่นๆ" ใน Odoo) ---
            gallery = conn.execute(
                "SELECT stored_name FROM Part_Images WHERE part_sku=? ORDER BY image_id", (sku,)
            ).fetchall()
            for idx, g in enumerate(gallery, start=1):
                src = os.path.join(PART_IMAGES_DIR, g["stored_name"])
                if os.path.isfile(src):
                    os.makedirs(part_dir, exist_ok=True)
                    with open(src, "rb") as img_f:
                        data = img_f.read()
                    gallery_name = f"gallery_{idx}" + safe_ext(g["stored_name"])
                    with open(os.path.join(part_dir, gallery_name), "wb") as out_f:
                        out_f.write(data)
                    images_copied += 1
                else:
                    missing_image_files.append(src)

            category_label = PRODUCT_CATEGORY_LABELS.get(p["category"], p["category"] or "")
            writer.writerow([
                sku,
                p["part_name"] or "",
                f"{p['cost_price'] or 0:.2f}",
                f"{p['cost_price'] or 0:.2f}",
                category_label,
                p["description"] or "",
                image_b64,
                p["stock_quantity"] if p["stock_quantity"] is not None else "",
                p["storage_location"] or "",
            ])
            rows_written += 1

    # --- zip โฟลเดอร์รูปทั้งหมดไว้ไฟล์เดียว ดาวน์โหลด/ส่งต่อสะดวก ---
    zip_path = os.path.join(out_dir, "product_images.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(images_out_dir):
            for fn in files:
                full = os.path.join(root, fn)
                arcname = os.path.relpath(full, images_out_dir)
                zf.write(full, arcname)

    readme_path = os.path.join(out_dir, "README_นำเข้า_Odoo.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(f"""วิธีนำเข้าสินค้าเข้า Odoo จากไฟล์ที่ export มา
================================================

สรุปจำนวน: ส่งออกสินค้า {rows_written} รายการ, คัดลอกรูปภาพ {images_copied} ไฟล์
{"ไฟล์รูปที่หาไม่เจอ (ข้ามไป ไม่รวมใน export): " + str(len(missing_image_files)) + " ไฟล์" if missing_image_files else ""}

ไฟล์ในโฟลเดอร์นี้:
  - products_odoo_import.csv  : ไฟล์หลักสำหรับนำเข้า Odoo (มีรูปปกฝังเป็น base64 มาในตัวแล้ว)
  - images/<SKU>/              : รูปจริงของสินค้าแต่ละชิ้น (cover.* = รูปปก, gallery_1.*, gallery_2.* = รูปแกลเลอรี)
  - product_images.zip         : รูปทั้งหมดรวมเป็นไฟล์ zip เดียว

ขั้นตอนนำเข้าใน Odoo:
1. เข้า Odoo > แอป Inventory (หรือ Sales) > Products > Products
2. กดปุ่ม "Favorites" (รูปดาว มุมขวาบนของตาราง) > "Import records"
   หรือกด "New" ค้างไว้แล้วเลือก "Import records" ก็ได้ (ขึ้นกับเวอร์ชัน Odoo)
3. อัปโหลดไฟล์ products_odoo_import.csv
4. หน้าจอ "แมปคอลัมน์" (Map your columns):
   - "Internal Reference"  -> Internal Reference (default_code)
   - "Name"                -> Name
   - "Sales Price"         -> Sales Price
   - "Cost"                -> Cost
   - "Product Category"    -> Product Category (ถ้าหมวดยังไม่มีในระบบ Odoo จะมีตัวเลือกให้ "สร้างใหม่" ระหว่าง import)
   - "Sales Description"   -> Sales Description / Description
   - "Image 1920"          -> Image (เลือกช่อง "รูปภาพ" ของสินค้า — Odoo จะถอดรหัส base64 ให้เป็นรูปอัตโนมัติ)
   - "สต็อกคงเหลือ (อ้างอิง)" และ "ตำแหน่งจัดเก็บ (อ้างอิง)" -> ติ๊ก "Don't import" (ไม่ใช่ฟิลด์มาตรฐานของ Odoo
     ใส่มาให้ดูอ้างอิงเฉยๆ ตอนเช็คข้อมูลเท่านั้น)
5. กด "Test" ก่อน 1 ครั้งเพื่อเช็คว่าไม่มีแถวไหน error แล้วค่อยกด "Import"

หมายเหตุสำคัญ:
- จำนวนสต็อกคงเหลือ (on-hand quantity) เป็นข้อมูลที่ Odoo แยกเก็บเป็นธุรกรรมคลังสินค้า (stock.quant) ไม่ใช่
  ฟิลด์ตรงของสินค้า จึง import พร้อมสินค้าทีเดียวไม่ได้ ต้องตั้งจำนวนเริ่มต้นเองทีหลังผ่านเมนู
  Inventory > Products > (เลือกสินค้า) > "Update Quantity" โดยดูตัวเลขอ้างอิงจากคอลัมน์
  "สต็อกคงเหลือ (อ้างอิง)" ในไฟล์ CSV
- รูปแกลเลอรี (gallery_1, gallery_2, ...) ต้องแนบเพิ่มเองทีหลังเป็นรายชิ้นผ่านแท็บ "รูปภาพอื่นๆ" (Extra Media)
  ของสินค้านั้นๆ ใน Odoo เพราะการ import แบบ CSV รองรับรูปได้แค่ 1 รูปต่อสินค้า (รูปปก) เท่านั้น
- ถ้า CSV ไฟล์ใหญ่เกินไป (รูปเยอะ/ไฟล์รูปใหญ่) จนนำเข้าทีเดียวไม่ไหวหรือช้ามาก ให้แบ่ง import เป็นชุดๆ
  โดยลบคอลัมน์ "Image 1920" ออกก่อน (นำเข้าแค่ข้อมูลตัวอักษร) แล้วค่อยแนบรูปทีละสินค้าทีหลังจากโฟลเดอร์ images/
""")

    print(f"เสร็จแล้ว — ส่งออกสินค้า {rows_written} รายการ, คัดลอกรูป {images_copied} ไฟล์")
    if missing_image_files:
        print(f"⚠️  หาไฟล์รูปไม่เจอ {len(missing_image_files)} ไฟล์ (ข้ามไปแล้ว):")
        for m in missing_image_files[:20]:
            print(f"   - {m}")
    print(f"ไฟล์ผลลัพธ์อยู่ที่: {out_dir}")
    print(f"  - {csv_path}")
    print(f"  - {zip_path}")
    print(f"  - {readme_path}")


if __name__ == "__main__":
    main()
