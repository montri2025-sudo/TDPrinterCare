"""Guarded PostgreSQL integration check; fictional local stack only. Never calls Odoo."""
import os
if os.environ.get('TDSP_LOCAL_TEST') != '1':
    raise SystemExit('Refusing to run outside the isolated local test stack')
import json
import uuid
import db
import field_service as fs

c=db.get_conn()
user=c.execute('SELECT * FROM Users WHERE username=?',(os.environ['INITIAL_ADMIN_USERNAME'],)).fetchone()
tech=c.execute("SELECT * FROM Users WHERE username='fs-local-technician'").fetchone()
device=c.execute("SELECT * FROM Devices WHERE device_sn='LOCAL-FS-TEST-001'").fetchone()
if not tech or not device:
    raise SystemExit('Set up fictional local customer/device/technician fixtures first')
# Observe existing workflows, including balances/stock, before every field-service write.
legacy=[r['tablename'] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        if not r['tablename'].startswith('field_service_')]
def fingerprint():
    return {t:json.dumps(sorted([json.dumps(dict(r),sort_keys=True,default=str) for r in c.execute('SELECT * FROM "'+t+'"').fetchall()]),sort_keys=True) for t in legacy}
before=fingerprint()
f=dict(center_id=str(tech['center_id']),customer_id=str(device['customer_id']),device_sn=device['device_sn'],
       service_type='inspection',site='LOCAL integration verification',address='Fictional local-only address',
       contact_name='Fictional contact',contact_phone='0000000000',symptom='Local persistent lifecycle check',
       appointment_date='2026-10-29',start_time='09:00',end_time='11:00',service_minutes='60',
       assigned_tech_id=str(tech['user_id']),request_key=uuid.uuid4().hex)
jid=fs.create(c,user,f)
assert fs.create(c,user,f)==jid
for target in ('awaiting_schedule','assigned','preparing','traveling','in_service'):
    j=fs.get_job(c,user,jid)
    fs.update(c,user,jid,dict(version=str(j['version']),action='status',to_status=target))
j=fs.get_job(c,user,jid)
fs.update(c,user,jid,dict(version=str(j['version']),action='report',report='Completed local inspection',**{'check_'+str(i):'on' for i in range(4)}))
for target in ('awaiting_acceptance','completed'):
    j=fs.get_job(c,user,jid)
    fs.update(c,user,jid,dict(version=str(j['version']),action='status',to_status=target,accepted_by='Fictional receiver'))
assert fs.get_job(c,user,jid)['status']=='completed'
try:
    fs.update(c,user,jid,dict(version='1',action='report',report='Stale content'))
except fs.Error as e:
    assert e.status==409
else:
    raise AssertionError('Stale update accepted')
assert before==fingerprint(), 'An existing-workflow table changed'
c.close()
# New connection: state/history are durable rather than session/browser state.
c=db.get_conn()
assert fs.get_job(c,user,jid)['report']=='Completed local inspection'
assert len(fs.events(c,jid))==9
c.close()
print('PASS: PostgreSQL durable lifecycle, report, history, duplicate submit, stale writes; existing tables unchanged.')
