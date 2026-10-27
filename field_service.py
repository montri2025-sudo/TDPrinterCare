"""Persistent field service. No Odoo, stock, billing or external-map side effects."""
import datetime as dt
import json
import math
import re
import uuid
import time

ROLES = ('admin', 'manager', 'technician_lead', 'technician', 'sales')
COORDINATORS = ('admin', 'manager', 'technician_lead', 'sales')
TYPES = {'install': 'ติดตั้ง', 'inspection': 'ตรวจเช็ก', 'repair': 'ซ่อม', 'maintenance': 'บำรุงรักษา'}
LABELS = {'requested': 'รับคำขอ', 'awaiting_schedule': 'รอนัดหมาย', 'assigned': 'มอบหมายช่าง',
          'preparing': 'เตรียมพร้อม', 'traveling': 'เดินทาง', 'in_service': 'กำลังบริการ',
          'awaiting_acceptance': 'รอตรวจรับ', 'completed': 'เสร็จสิ้น',
          'waiting_parts': 'รออะไหล่', 'returned_to_center': 'นำเครื่องกลับศูนย์'}
TRANSITIONS = {'requested': ['awaiting_schedule'], 'awaiting_schedule': ['assigned'],
               'assigned': ['preparing'], 'preparing': ['traveling', 'waiting_parts'],
               'traveling': ['in_service'], 'in_service': ['awaiting_acceptance', 'waiting_parts', 'returned_to_center'],
               'waiting_parts': ['preparing'], 'awaiting_acceptance': ['completed', 'in_service'],
               'completed': [], 'returned_to_center': []}
CHECKS = {'install': ['ตรวจพื้นที่และไฟเลี้ยง', 'ประกอบและปรับระดับเครื่อง', 'ทดสอบพิมพ์', 'สอนผู้ใช้งาน'],
          'inspection': ['ตรวจสายไฟ', 'ตรวจแกน', 'ตรวจอุณหภูมิ', 'สรุปผลตรวจ'],
          'repair': ['ยืนยันอาการ', 'ตรวจสาเหตุ', 'แก้ไขปัญหา', 'ทดสอบหลังซ่อม'],
          'maintenance': ['ทำความสะอาด', 'หล่อลื่นราง', 'ตรวจสายพาน', 'ปรับเทียบและทดสอบ']}


class Error(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime('%Y-%m-%d %H:%M:%S')


def text(form, key, limit=1000, required=False):
    value = str(form.get(key) or '').strip()
    if (required and not value) or len(value) > limit:
        raise Error(400, 'กรุณาตรวจข้อมูลช่อง ' + key)
    return value


def integer(value, name, minimum=1, maximum=2147483647):
    try:
        if not re.fullmatch(r'\d+', str(value)):
            raise ValueError()
        n = int(value)
        if n < minimum or n > maximum:
            raise ValueError()
        return n
    except (ValueError, TypeError):
        raise Error(400, 'ค่า ' + name + ' ไม่ถูกต้อง') from None


def authorize(user):
    if not user or user['role'] not in ROLES:
        raise Error(403, 'ไม่มีสิทธิ์เข้าถึงบริการนอกสถานที่')
    if user['role'] != 'admin' and not user.get('center_id'):
        raise Error(403, 'กรุณาให้ผู้ดูแลกำหนดสาขาของบัญชีนี้ก่อน')


def scope(user, alias='j'):
    authorize(user)
    if user['role'] == 'admin':
        return '1=1', ()
    sql, params = f'{alias}.center_id=?', (user['center_id'],)
    if user['role'] == 'technician':
        sql += f' AND {alias}.assigned_tech_id=?'
        params += (user['user_id'],)
    return sql, params


def get_job(conn, user, job_id):
    where, params = scope(user)
    row = conn.execute('SELECT j.*, c.name AS customer_name, d.model, u.name AS tech_name, sc.name AS center_name '
                       'FROM Field_Service_Jobs j JOIN Customers c ON c.customer_id=j.customer_id '
                       'JOIN Devices d ON d.device_sn=j.device_sn JOIN Service_Centers sc ON sc.center_id=j.center_id '
                       'LEFT JOIN Users u ON u.user_id=j.assigned_tech_id WHERE j.job_id=? AND ' + where,
                       (job_id,) + params).fetchone()
    if not row:
        raise Error(404, 'ไม่พบใบงานหรือไม่มีสิทธิ์เข้าถึง')
    return dict(row)


def options(conn, user):
    authorize(user)
    if user['role'] == 'technician':
        return [], [], [], []
    # Customer/device masters are shared across branches in the existing customer-management feature.
    customers = conn.execute('SELECT customer_id,name,address,phone FROM Customers ORDER BY name').fetchall()
    devices = conn.execute("SELECT device_sn,customer_id,model FROM Devices WHERE status='Active' ORDER BY model,device_sn").fetchall()
    where, args = ('', ()) if user['role'] == 'admin' else (' WHERE center_id=?', (user['center_id'],))
    centers = conn.execute('SELECT center_id,name,latitude,longitude FROM Service_Centers' + where + ' ORDER BY name', args).fetchall()
    techs = conn.execute("SELECT user_id,name,center_id FROM Users WHERE is_active=1 AND role IN ('technician','technician_lead')" +
                         ('' if user['role'] == 'admin' else ' AND center_id=?') + ' ORDER BY name', args).fetchall()
    return [dict(x) for x in customers], [dict(x) for x in devices], [dict(x) for x in centers], [dict(x) for x in techs]


def appointment(form):
    date = text(form, 'appointment_date', 10)
    start, end = text(form, 'start_time', 5), text(form, 'end_time', 5)
    if not date:
        if start or end:
            raise Error(400, 'กรุณาระบุวันนัดพร้อมเวลา')
        return None, None, None
    try:
        if dt.date.fromisoformat(date).isoformat() != date:
            raise ValueError()
        for t in (start, end):
            if not re.fullmatch(r'\d{2}:\d{2}', t):
                raise ValueError()
            dt.time.fromisoformat(t)
        if start >= end:
            raise ValueError()
    except ValueError:
        raise Error(400, 'วันนัดหรือช่วงเวลาไม่ถูกต้อง') from None
    return date, start, end


def tech(conn, raw, center):
    if not raw:
        return None
    uid = integer(raw, 'ช่าง')
    row = conn.execute("SELECT user_id FROM Users WHERE user_id=? AND center_id=? AND is_active=1 "
                       "AND role IN ('technician','technician_lead')", (uid, center)).fetchone()
    if not row:
        raise Error(400, 'ช่างต้องเป็นบัญชีที่ใช้งานอยู่ในสาขาของใบงาน')
    return uid


def history(conn, user, job_id, old, new, note):
    conn.execute('INSERT INTO Field_Service_History (event_id,job_id,from_status,to_status,note,changed_by,changed_at) '
                 'VALUES (?,?,?,?,?,?,?)', (f'{time.time_ns():020d}'+uuid.uuid4().hex[:12], job_id, old, new, note, user['user_id'], now()))


def create(conn, user, form):
    authorize(user)
    if user['role'] not in COORDINATORS:
        raise Error(403, 'ช่างทั่วไปสร้างใบงานไม่ได้')
    center = integer(form.get('center_id'), 'สาขา')
    if user['role'] != 'admin' and center != user['center_id']:
        raise Error(403, 'สร้างใบงานได้เฉพาะสาขาของตนเอง')
    if not conn.execute('SELECT center_id FROM Service_Centers WHERE center_id=?', (center,)).fetchone():
        raise Error(400, 'ไม่พบสาขา')
    cid = integer(form.get('customer_id'), 'ลูกค้า')
    sn = text(form, 'device_sn', 64, True)
    if not conn.execute("SELECT device_sn FROM Devices WHERE device_sn=? AND customer_id=? AND status='Active'", (sn, cid)).fetchone():
        raise Error(400, 'เครื่องต้องเป็นของลูกค้าที่เลือกและยังใช้งานอยู่')
    typ = text(form, 'service_type', 20, True)
    if typ not in TYPES:
        raise Error(400, 'ประเภทบริการไม่ถูกต้อง')
    date, start, end = appointment(form)
    uid = tech(conn, form.get('assigned_tech_id'), center)
    minutes = integer(form.get('service_minutes'), 'เวลาบริการ', 5, 1440)
    site, address = text(form, 'site', 200, True), text(form, 'address', 2000, True)
    contact, phone = text(form, 'contact_name', 200, True), text(form, 'contact_phone', 100, True)
    symptom = text(form, 'symptom', 5000, True)
    coords = []
    for key, bound in (('latitude', 90), ('longitude', 180)):
        raw = text(form, key, 30)
        try:
            val = float(raw) if raw else None
            if val is not None and (not math.isfinite(val) or abs(val) > bound):
                raise ValueError()
        except ValueError:
            raise Error(400, 'พิกัดไม่ถูกต้อง') from None
        coords.append(val)
    if (coords[0] is None) != (coords[1] is None):
        raise Error(400, 'กรุณาระบุทั้งละติจูดและลองจิจูด')
    # Request-specific key prevents double submission/reload creating another job.
    key = text(form, 'request_key', 32, True)
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise Error(400, 'คำขอหมดอายุ กรุณาเปิดแบบฟอร์มใหม่')
    job_id = 'FS-' + key
    existing = conn.execute('SELECT created_by FROM Field_Service_Jobs WHERE job_id=?', (job_id,)).fetchone()
    if existing:
        if existing['created_by'] != user['user_id']:
            raise Error(409, 'คำขอนี้ถูกใช้แล้ว')
        get_job(conn, user, job_id)
        return job_id
    stamp = now()
    inserted = conn.execute('INSERT INTO Field_Service_Jobs (job_id,center_id,customer_id,device_sn,service_type,site,address,contact_name,contact_phone,'
                 'latitude,longitude,symptom,appointment_date,start_time,end_time,service_minutes,assigned_tech_id,created_by,created_at,updated_at) '
                 'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (job_id) DO NOTHING',
                 (job_id,center,cid,sn,typ,site,address,contact,phone,*coords,symptom,date,start,end,minutes,uid,user['user_id'],stamp,stamp))
    if inserted.rowcount != 1:
        existing = get_job(conn,user,job_id)
        if existing['created_by'] != user['user_id']:
            raise Error(409,'คำขอนี้ถูกใช้แล้ว')
        return job_id
    history(conn, user, job_id, None, 'requested', 'สร้างใบงานบริการนอกสถานที่')
    conn.commit()
    return job_id


def update(conn, user, job_id, form):
    j = get_job(conn, user, job_id)
    version = integer(form.get('version'), 'รุ่นข้อมูล')
    if version != j['version']:
        raise Error(409, 'ข้อมูลเปลี่ยนแล้ว กรุณาโหลดใหม่ก่อนบันทึก')
    action = text(form, 'action', 20, True)
    role = user['role']
    note, to = '', j['status']
    values = {}
    if action == 'schedule':
        if role not in COORDINATORS:
            raise Error(403, 'ไม่มีสิทธิ์จัดตารางหรือมอบหมายงาน')
        if j['status'] not in ('requested','awaiting_schedule','assigned','preparing','traveling','waiting_parts'):
            raise Error(400, 'สถานะนี้เปลี่ยนนัดไม่ได้')
        date, start, end = appointment(form)
        if not date:
            raise Error(400, 'กรุณาระบุวันและเวลานัด')
        uid = tech(conn, form.get('assigned_tech_id'), j['center_id'])
        reason = text(form, 'reason', 1000, True)
        if j['status'] not in ('requested','awaiting_schedule') and not uid:
            raise Error(400, 'กรุณาระบุช่างสำหรับงานที่มอบหมายแล้ว')
        to = ('assigned' if uid else 'awaiting_schedule') if j['status'] != 'requested' else 'requested'
        values = {'appointment_date':date,'start_time':start,'end_time':end,'assigned_tech_id':uid,
                  'service_minutes':integer(form.get('service_minutes'), 'เวลาบริการ', 5, 1440)}
        note = f"ปรับนัด/ผู้รับผิดชอบ: {j['appointment_date'] or '-'} {j['start_time'] or '-'} → {date} {start}–{end}; ช่าง {j['assigned_tech_id'] or '-'} → {uid or '-'}; {reason}"
    elif action == 'report':
        if role == 'sales':
            raise Error(403, 'เซลส์ไม่มีสิทธิ์แก้รายงานช่าง')
        if j['status'] in ('completed','returned_to_center'):
            raise Error(400, 'ใบงานปิดแล้ว แก้รายงานไม่ได้')
        checks = {str(i): form.get('check_' + str(i)) == 'on' for i in range(len(CHECKS[j['service_type']]))}
        values = {'report':text(form, 'report', 10000), 'checklist':json.dumps(checks)}
        note = 'บันทึกรายงานบริการและ Checklist'
    elif action == 'status':
        to = text(form, 'to_status', 30, True)
        if to not in TRANSITIONS[j['status']]:
            raise Error(400, 'เปลี่ยนสถานะข้ามขั้นตอนไม่ได้')
        if role == 'sales' and (j['status'],to) not in (('requested','awaiting_schedule'),('awaiting_schedule','assigned')):
            raise Error(403, 'เซลส์จัดคิวได้ แต่เปลี่ยนขั้นตอนทำงานช่างไม่ได้')
        if role == 'technician' and j['status'] in ('requested','awaiting_schedule'):
            raise Error(403, 'ให้ผู้ประสานงานยืนยันนัดและมอบหมายช่างก่อน')
        note = text(form, 'reason', 1000)
        if (to in ('waiting_parts','returned_to_center') or (j['status'] == 'awaiting_acceptance' and to == 'in_service')) and not note:
            raise Error(400, 'กรุณาระบุเหตุผล')
        if to == 'assigned' and (not j['assigned_tech_id'] or not j['appointment_date']):
            raise Error(400, 'ต้องระบุช่างและวันนัดก่อน')
        if to in ('awaiting_acceptance','completed'):
            checks = json.loads(j['checklist'])
            if not j['report'].strip() or not all(checks.get(str(i)) for i in range(len(CHECKS[j['service_type']]))):
                raise Error(400, 'กรุณาบันทึกรายงานและทำ Checklist ให้ครบก่อนส่งตรวจรับ')
        if to == 'completed':
            receiver = text(form, 'accepted_by', 200, True)
            note = 'ผู้ตรวจรับ: ' + receiver + ('; ' + note if note else '')
        values = {'status':to}
    else:
        raise Error(400, 'คำสั่งไม่ถูกต้อง')
    values['status'] = to
    values['updated_at'] = now()
    columns = ','.join(k + '=?' for k in values)
    cur = conn.execute('UPDATE Field_Service_Jobs SET ' + columns + ',version=version+1 WHERE job_id=? AND version=?',
                       tuple(values.values()) + (job_id,version))
    if cur.rowcount != 1:
        raise Error(409, 'มีผู้ใช้อื่นแก้ไขใบงาน กรุณาโหลดใหม่')
    history(conn, user, job_id, j['status'], to, note or LABELS[to])
    conn.commit()


def listing(conn, user):
    where, params = scope(user)
    return [dict(r) for r in conn.execute('SELECT j.*,c.name AS customer_name,d.model,u.name AS tech_name,s.name AS center_name '
        'FROM Field_Service_Jobs j JOIN Customers c ON c.customer_id=j.customer_id JOIN Devices d ON d.device_sn=j.device_sn '
        'JOIN Service_Centers s ON s.center_id=j.center_id LEFT JOIN Users u ON u.user_id=j.assigned_tech_id '
        'WHERE ' + where + ' ORDER BY j.appointment_date DESC,j.created_at DESC', params).fetchall()]


def events(conn, job_id):
    return [dict(r) for r in conn.execute('SELECT h.*,u.name AS actor FROM Field_Service_History h '
             'JOIN Users u ON u.user_id=h.changed_by WHERE h.job_id=? ORDER BY h.changed_at,h.event_id', (job_id,)).fetchall()]


def plan_data(conn, user, center, uid, date):
    authorize(user)
    center, uid = integer(center, 'สาขา'), integer(uid, 'ช่าง')
    if user['role'] != 'admin' and center != user['center_id']:
        raise Error(403, 'ไม่มีสิทธิ์ดูแผนของสาขาอื่น')
    if user['role'] == 'technician' and uid != user['user_id']:
        raise Error(403, 'ช่างดูแผนของตนเองได้เท่านั้น')
    tech(conn, uid, center)
    try:
        if dt.date.fromisoformat(date).isoformat() != date:
            raise ValueError()
    except (ValueError, TypeError):
        raise Error(400, 'วันที่แผนไม่ถูกต้อง') from None
    row = conn.execute('SELECT * FROM Field_Service_Plans WHERE center_id=? AND tech_id=? AND plan_date=?', (center,uid,date)).fetchone()
    return dict(row) if row else None


def save_plan(conn, user, form):
    center, uid, date = form.get('center_id'), form.get('tech_id'), form.get('plan_date')
    old = plan_data(conn, user, center, uid, date)
    version = integer(form.get('version'), 'รุ่นแผน', 0)
    if version != (old['version'] if old else 0):
        raise Error(409, 'แผนเปลี่ยนแล้ว กรุณาโหลดแผนใหม่')
    try:
        order = json.loads(text(form, 'order', 10000, True))
        if not isinstance(order,list) or len(order)>30 or len(set(order))!=len(order) or any(not isinstance(i,str) for i in order):
            raise ValueError()
    except (ValueError, TypeError):
        raise Error(400, 'ลำดับจุดแวะไม่ถูกต้อง') from None
    for jid in order:
        job = get_job(conn, user, jid)
        if job['center_id'] != int(center) or job['assigned_tech_id'] != int(uid) or job['appointment_date'] != date or job['status'] in ('completed','returned_to_center'):
            raise Error(400, 'จุดแวะต้องเป็นงานที่ยังไม่ปิดของช่าง สาขา และวันที่ในแผน')
    depart, end = text(form, 'depart',5,True), text(form, 'work_end',5,True)
    try:
        for value in (depart,end):
            if not re.fullmatch(r'\d{2}:\d{2}', value):
                raise ValueError()
            dt.time.fromisoformat(value)
        if depart >= end:
            raise ValueError()
    except ValueError:
        raise Error(400, 'ช่วงเวลาทำงานไม่ถูกต้อง') from None
    if form.get('end') not in ('return','last'):
        raise Error(400, 'จุดสิ้นสุดไม่ถูกต้อง')
    payload = json.dumps({'order':order,'depart':depart,'work_end':end,'end':form['end']}, ensure_ascii=False)
    if old:
        cur = conn.execute('UPDATE Field_Service_Plans SET payload=?,version=version+1,updated_by=?,updated_at=? WHERE plan_id=? AND version=?',
                     (payload,user['user_id'],now(),old['plan_id'],version))
        if cur.rowcount != 1:
            raise Error(409,'แผนเปลี่ยนแล้ว กรุณาโหลดใหม่')
    else:
        inserted = conn.execute('INSERT INTO Field_Service_Plans (plan_id,center_id,tech_id,plan_date,payload,updated_by,updated_at) VALUES (?,?,?,?,?,?,?)',
                     (uuid.uuid4().hex,int(center),int(uid),date,payload,user['user_id'],now()))
        if inserted.rowcount != 1:
            raise Error(409,'มีแผนใหม่แล้ว กรุณาโหลดใหม่')
    conn.commit()
