# image ทางการของ Odoo + wrapper บางๆ ที่ตั้งค่า admin_passwd (Master Password) ให้อัตโนมัติจาก
# ตัวแปรแวดล้อม ODOO_MASTER_PASSWORD ทุกครั้งที่ container เริ่มทำงาน (ดู entrypoint-wrapper.sh)
# ทำให้ย้ายไปเซิร์ฟเวอร์ใหม่ได้ง่าย — ไม่ต้องเข้าเว็บตั้ง Master Password ใหม่ทุกครั้งที่ deploy
FROM odoo:19.0

COPY --chmod=755 entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
CMD ["odoo"]
