"""Persistent field service: lifecycle, branch/assignee access, CSRF and stale-write prevention."""
import json
import sqlite3
import uuid
from unittest.mock import patch
import test_integration_api as fixtures
import test_virtual_office as office
import field_service as fs
import app


class TestFieldServiceLive(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.tokens=[]
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active) VALUES (99,'fs-admin','unused','admin','Admin',1)")
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active,center_id) VALUES (98,'fs-sales','unused','sales','Sales',1,1)")
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active,center_id) VALUES (97,'fs-sales-b','unused','sales','Other Sales',1,2)")
    def tearDown(self):
        for token in self.tokens: app.SESSIONS.pop(token,None)
        super().tearDown()
    def request(self,*args,**kwargs):
        return office.TestVirtualOffice.request(self,*args,**kwargs)
    def user(self,uid):
        conn=office.OfficeConn(self.path)
        try:return conn.execute('SELECT * FROM Users WHERE user_id=?',(uid,)).fetchone()
        finally:conn.close()
    def form(self,**overrides):
        f=dict(center_id='1',customer_id='1',device_sn='FAKE-SN-0001',service_type='maintenance',site='Fictional Factory',
            address='Fictional street',contact_name='Fictional contact',contact_phone='02-000-0000',symptom='Inspect rails',
            appointment_date='2026-10-28',start_time='10:00',end_time='12:00',service_minutes='60',assigned_tech_id='11',
            request_key=uuid.uuid4().hex,latitude='13.80',longitude='100.66')
        f.update(overrides);return f
    def create(self,uid=99,**overrides):
        conn=office.OfficeConn(self.path)
        try:return fs.create(conn,self.user(uid),self.form(**overrides))
        finally:conn.close()
    def job(self,jid,uid=99):
        conn=office.OfficeConn(self.path)
        try:return fs.get_job(conn,self.user(uid),jid)
        finally:conn.close()
    def update(self,jid,uid=99,**fields):
        f={'version':str(self.job(jid)['version'])};f.update(fields)
        return self.request('/field-service/jobs/'+jid,user_id=uid,method='POST',fields=f)

    def test_menu_real_records_and_demo_separate(self):
        for uid in (99,21,12,11,98):
            status,_,html=self.request('/field-service',user_id=uid,query='')
            self.assertEqual(status,200)
            self.assertIn('ข้อมูลบันทึกในระบบ',html)
            self.assertNotIn('บริการนอกสถานที่ (Demo)',html)
            self.assertNotIn('บริษัท สมมติพลาสติก',html)
            self.assertNotIn('sessionStorage',html)
        self.assertEqual(self.request('/field-service',user_id=20)[0],403)
        self.assertEqual(self.request('/field-service',user_id=None)[0],302)
        status,headers,_=self.request('/field-service/demo',user_id=99)
        self.assertEqual(status,302)
        self.assertEqual(headers['Location'],'/field-service')
        self.assertNotIn('href="/field-service/demo"',self.request('/field-service',user_id=99)[2])

    def test_create_persists_duplicate_form_and_validates_owner_branch_tech(self):
        f=self.form()
        for _ in range(2):
            status,headers,_=self.request('/field-service/new',user_id=98,method='POST',fields=f)
            self.assertEqual(status,302)
        jid='FS-'+f['request_key'];self.assertEqual(self.job(jid)['contact_name'],f['contact_name'])
        conn=office.OfficeConn(self.path)
        self.assertEqual(len(fs.events(conn,jid)),1);conn.close()
        for bad in ({'center_id':'2'},{'assigned_tech_id':'31'},{'assigned_tech_id':'13'},
                    {'customer_id':'999'},{'start_time':'14:00','end_time':'12:00'},
                    {'latitude':'nan'},{'longitude':''},{'appointment_date':'2026-02-31'}):
            status,_,_=self.request('/field-service/new',user_id=98,method='POST',fields=self.form(**bad))
            self.assertIn(status,(400,403),bad)
        self.assertEqual(self.request('/field-service/new',user_id=11,method='POST',fields=f)[0],403)
        self.assertEqual(self.request('/field-service/new',user_id=98,method='POST',fields=self.form(),csrf=False)[0],403)

    def test_scope_technician_assignee_and_cross_branch_sales(self):
        own=self.create();other=self.create(center_id='2',assigned_tech_id='31',site='PRIVATE_OTHER_FACTORY')
        unassigned=self.create(assigned_tech_id='',site='UNASSIGNED_PRIVATE')
        for uid in (21,12,98,11):
            html=self.request('/field-service',user_id=uid,query='')[2]
            self.assertIn('Fictional Factory',html)
            self.assertNotIn('PRIVATE_OTHER_FACTORY',html)
            self.assertEqual(self.request('/field-service/jobs/'+other,user_id=uid)[0],404)
            self.assertEqual(self.update(other,uid,action='report',report='tamper')[0],404)
        self.assertEqual(self.request('/field-service/jobs/'+own,user_id=97)[0],404)
        self.assertNotIn('UNASSIGNED_PRIVATE',self.request('/field-service',user_id=11,query='')[2])
        self.assertEqual(self.request('/field-service/jobs/'+unassigned,user_id=11)[0],404)
        self.assertEqual(self.request('/field-service',user_id=41,query='')[0],403)

    def test_full_flow_report_gate_real_actor_history_and_no_financial_side_effect(self):
        jid=self.create()
        for target in ('awaiting_schedule','assigned','preparing','traveling','in_service'):
            self.assertEqual(self.update(jid,action='status',to_status=target)[0],302,target)
        self.assertEqual(self.update(jid,11,action='status',to_status='awaiting_acceptance')[0],400)
        self.assertEqual(self.update(jid,11,action='report',report='Completed rail maintenance',**{'check_'+str(i):'on' for i in range(4)})[0],302)
        self.assertEqual(self.update(jid,11,action='status',to_status='awaiting_acceptance')[0],302)
        self.assertEqual(self.update(jid,action='status',to_status='completed')[0],400)
        self.assertEqual(self.update(jid,action='status',to_status='completed',accepted_by='Fictional receiver')[0],302)
        self.assertEqual(self.job(jid)['status'],'completed')
        self.assertEqual(self.update(jid,action='report',report='rewrite')[0],400)
        conn=office.OfficeConn(self.path);events=fs.events(conn,jid)
        self.assertEqual([e['to_status'] for e in events if e['from_status']!=e['to_status']],
                         ['requested','awaiting_schedule','assigned','preparing','traveling','in_service','awaiting_acceptance','completed'])
        self.assertTrue(all(e['actor']!='Demo' for e in events))
        self.assertEqual(conn.execute("SELECT stock_quantity FROM Spare_Parts WHERE part_sku='FAKE-SKU-1'").fetchone()['stock_quantity'],10)
        self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM Sales_Orders').fetchone()['n'],0);conn.close()
        self.assertIn('Completed rail maintenance',self.request('/field-service/jobs/'+jid,user_id=11)[2])

    def test_stale_version_csrf_sales_cannot_write_report_or_service_status(self):
        jid=self.create()
        self.assertEqual(self.update(jid,98,action='report',report='tamper')[0],403)
        self.assertEqual(self.update(jid,action='status',to_status='completed')[0],400)
        self.assertEqual(self.update(jid,98,action='status',to_status='awaiting_schedule')[0],302)
        self.assertEqual(self.update(jid,98,action='status',to_status='assigned')[0],302)
        self.assertEqual(self.update(jid,98,action='status',to_status='preparing')[0],403)
        self.assertEqual(self.update(jid,action='report',version='1',report='stale')[0],409)
        self.assertEqual(self.request('/field-service/jobs/'+jid,user_id=99,method='POST',csrf=False,fields={'action':'report','version':str(self.job(jid)['version'])})[0],403)

    def test_schedule_reason_and_assignment_are_audited(self):
        jid=self.create()
        fields=dict(action='schedule',appointment_date='2026-10-29',start_time='11:00',end_time='13:00',service_minutes='90',assigned_tech_id='12')
        self.assertEqual(self.update(jid,98,**fields)[0],400)
        self.assertEqual(self.update(jid,98,reason='Customer requested change',**fields)[0],302)
        self.assertEqual((self.job(jid)['appointment_date'],self.job(jid)['assigned_tech_id']),('2026-10-29',12))
        self.assertEqual(self.request('/field-service/jobs/'+jid,user_id=11)[0],404)
        html=self.request('/field-service/jobs/'+jid,user_id=12)[2]
        self.assertIn('Customer requested change',html)
        self.assertIn('2026-10-28',html)

    def test_persistent_route_plan_validation_scope_and_stale_version(self):
        ids=[self.create(site='Factory '+str(i)) for i in range(3)]
        data=dict(center_id='1',tech_id='11',plan_date='2026-10-28',version='0',order=json.dumps(ids),depart='08:30',work_end='17:30',end='return')
        self.assertEqual(self.request('/field-service/plans',user_id=11,method='POST',fields=data)[0],302)
        status,_,html=self.request('/field-service/plans',user_id=11,query='center_id=1&tech_id=11&plan_date=2026-10-28')
        self.assertEqual(status,200);self.assertIn(ids[0],html)
        self.assertIn('version" value="1"',html)
        self.assertEqual(self.request('/field-service/plans',user_id=11,method='POST',fields=data)[0],409)
        self.assertEqual(self.request('/field-service/plans',user_id=97,query='center_id=1&tech_id=11&plan_date=2026-10-28')[0],403)
        self.assertEqual(self.request('/field-service/plans',user_id=11,query='center_id=1&tech_id=12&plan_date=2026-10-28')[0],403)
        for order in ([ids[0],ids[0]],['FS-'+'f'*32],['malicious'],{}):
            bad=dict(data,order=json.dumps(order),version='1')
            self.assertIn(self.request('/field-service/plans',user_id=11,method='POST',fields=bad)[0],(400,404))
        bad=dict(data,tech_id='12',order=json.dumps(ids))
        self.assertEqual(self.request('/field-service/plans',user_id=99,method='POST',fields=bad)[0],400)

    def test_html_escaping_and_no_google_or_real_location_transmission(self):
        jid=self.create(site='<script>alert(1)</script>')
        html=self.request('/field-service/jobs/'+jid,user_id=99)[2]
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('&lt;script&gt;',html)
        from pathlib import Path
        js=(Path(__file__).resolve().parents[1]/'static/field-service-live.js').read_text()
        for banned in ('fetch(', 'XMLHttpRequest', 'sessionStorage', 'navigator.geolocation', 'maps.googleapis.com'):
            self.assertNotIn(banned,js)
