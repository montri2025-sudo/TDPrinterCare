#!/bin/bash
# entrypoint-wrapper.sh — ครอบ entrypoint เดิมของ image odoo ทางการ (/entrypoint.sh) อีกชั้นหนึ่ง
# เพื่อเขียนค่า admin_passwd (Master Password ของหน้า Database Manager, /web/database/manager) ลงใน
# odoo.conf จากตัวแปรแวดล้อม ODOO_MASTER_PASSWORD "ทุกครั้ง" ที่ container เริ่มทำงาน
#
# เหตุผลที่ต้องทำแบบนี้: image ทางการของ Odoo ไม่มีตัวแปรแวดล้อมสำหรับตั้ง admin_passwd ให้ตรงๆ
# (มีให้แค่ HOST/PORT/USER/PASSWORD สำหรับต่อฐานข้อมูล) ถ้าไม่ตั้งค่านี้ไว้ล่วงหน้า ผู้ใช้ต้องเข้าไปตั้ง
# ผ่านหน้าเว็บ database manager เองตอนติดตั้งครั้งแรก ทำให้รหัสผ่านนี้ไม่แน่นอน/ไม่ portable ข้ามเซิร์ฟเวอร์
# การเขียนจาก .env ทุกครั้งที่สตาร์ทแบบนี้ทำให้ย้ายไปเซิร์ฟเวอร์ใหม่ได้ง่าย — แค่พก .env (หรือค่า
# ODOO_MASTER_PASSWORD เดียวกัน) ไปด้วย รหัสผ่านนี้ก็จะเหมือนเดิมทุกครั้งโดยไม่ต้องตั้งค่าผ่านเว็บใหม่เลย
set -e

CONF="${ODOO_RC:-/etc/odoo/odoo.conf}"

if [ -n "$ODOO_MASTER_PASSWORD" ]; then
    if [ -f "$CONF" ] && grep -q '^\[options\]' "$CONF"; then
        # ลบบรรทัด admin_passwd เดิม (ถ้ามี) ออกก่อน แล้วแทรกบรรทัดใหม่ต่อจาก [options] — ใช้ awk แทน sed
        # เพื่อเลี่ยงปัญหาอักขระพิเศษในรหัสผ่าน (เช่น @, &, /) ที่จะไปชนกับ syntax ของ sed
        grep -v -E '^\s*admin_passwd\s*=' "$CONF" > "${CONF}.tmp"
        awk -v pw="$ODOO_MASTER_PASSWORD" '
            /^\[options\]/ && !done { print; print "admin_passwd = " pw; done=1; next }
            { print }
        ' "${CONF}.tmp" > "$CONF"
        rm -f "${CONF}.tmp"
    else
        { echo "[options]"; echo "admin_passwd = ${ODOO_MASTER_PASSWORD}"; } >> "$CONF"
    fi
fi

exec /entrypoint.sh "$@"
