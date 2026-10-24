"""Virtual Office regressions. Isolated SQLite and fictional fixtures only."""
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlencode
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests'), str(ROOT/'tests'/'_stubs')]
import app
import test_integration_api as fixtures


class OfficeConn:
    def __init__(self, path):
        self.raw = sqlite3.connect(path)
        self.raw.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
    def execute(self, sql, params=()): return self.raw.execute(sql, params)
    def commit(self): self.raw.commit()
    def close(self): self.raw.close()


class TestVirtualOffice(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (99,'fictional-admin','fictional','admin','Fiction Admin',1)")
        self.tokens = []

    def tearDown(self):
        for token in self.tokens: app.SESSIONS.pop(token, None)
        super().tearDown()

    def request(self, path='/admin/board', *, user_id=99, method='GET', fields=None, query='from=2026-10-01&to=2026-10-31', csrf=True):
        token = 'fictional-office-' + str(user_id)
        self.tokens.append(token)
        app.SESSIONS[token] = {'user_id':user_id,'csrf_token':'fictional-office-csrf','created':time.time(),'last_seen':time.time()}
        params = dict(fields or {})
        if method == 'POST' and csrf: params['csrf_token'] = 'fictional-office-csrf'
        body = urlencode(params).encode()
        environ = {'PATH_INFO':path,'QUERY_STRING':query,'REQUEST_METHOD':method,
                   'CONTENT_LENGTH':str(len(body)),'CONTENT_TYPE':'application/x-www-form-urlencoded',
                   'wsgi.input':io.BytesIO(body),'HTTP_COOKIE':'sid='+token,'REMOTE_ADDR':'192.0.2.10'}
        captured = {}
        with patch.object(app.db, 'get_conn', side_effect=lambda:OfficeConn(self.path)):
            result = app.application(environ, lambda status, headers:captured.update(status=int(status.split()[0]),headers=dict(headers)))
        return captured['status'], captured['headers'], b''.join(result).decode()

    def ticket(self, ticket_id):
        conn=OfficeConn(self.path)
        try:return conn.execute('SELECT * FROM Tickets WHERE ticket_id=?',(ticket_id,)).fetchone()
        finally:conn.close()

    def payload(self, html):
        return json.loads(re.search(r'id="office-data">(.*?)</script>',html,re.S).group(1))

    def update(self, tid, **fields):
        current=self.ticket(tid)
        params={'status':current['status'],'assigned_tech_id':current['assigned_tech_id'] or '',
                'expected_status':current['status'],'expected_tech_id':current['assigned_tech_id'] or '',
                'expected_handover':current['handover_status'],'handover_status':current['handover_status'],
                'next':'/admin/board?from=2026-10-01&to=2026-10-31&updated='+str(tid)}
        params.update(fields)
        return self.request('/admin/ticket/'+str(tid)+'/update',method='POST',fields=params)

    def test_board_contains_scene_real_history_and_safe_json(self):
        malicious='</script><img src=x onerror="throw 1">'
        self.mutate('UPDATE Customers SET name=?',(malicious,))
        status,_,html=self.request()
        self.assertEqual(status,200)
        self.assertIn('id="office-scene"',html)
        self.assertIn('office-mode',html)
        self.assertNotIn(malicious,html)
        tickets=self.payload(html)['tickets']
        self.assertEqual(len(tickets),10)
        self.assertTrue(all(t['handover_status']=='unrecorded' for t in tickets))
        self.assertEqual(next(t for t in tickets if t['ticket_id']==102)['history'][0]['status'],app.db.STATUS_LABELS['In Repair'])
        self.assertEqual(tickets[0]['customer_name'],malicious)
        self.assertIn('Virtual Office',html)
        self.assertNotIn('>Kanban Board<',html)

    def test_manager_only_sees_own_center(self):
        status,_,html=self.request(user_id=21)
        self.assertEqual(status,200)
        payload=self.payload(html)
        self.assertTrue(all(t['center_id']==1 for t in payload['tickets']))
        self.assertNotIn(108,[t['ticket_id'] for t in payload['tickets']])
        self.assertTrue(all(t['center_id']==1 for t in payload['techs']))

    def test_unassigned_manager_and_empty_dates_show_empty_scene(self):
        self.mutate('UPDATE Users SET center_id=NULL WHERE user_id=21')
        status,_,html=self.request(user_id=21)
        self.assertEqual(status,200)
        self.assertEqual(self.payload(html)['tickets'],[])
        status,_,html=self.request(query='from=2000-01-01&to=2000-01-31')
        self.assertEqual(status,200)
        self.assertEqual(self.payload(html)['tickets'],[])

    def test_customer_and_technician_cannot_manage_office(self):
        for uid in (20,11):
            self.assertEqual(self.request(user_id=uid)[0],403)

    def test_status_update_assigns_tech_records_history_and_returns_to_date_range(self):
        status,headers,_=self.update(101,status='Diagnosing',assigned_tech_id=11)
        self.assertEqual(status,302)
        self.assertIn('from=2026-10-01',headers['Location'])
        self.assertIn('updated=101',headers['Location'])
        self.assertEqual(self.ticket(101)['status'],'Diagnosing')
        self.assertEqual(self.ticket(101)['assigned_tech_id'],11)
        conn=OfficeConn(self.path)
        try:self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM Ticket_Status_History WHERE ticket_id=101').fetchone()['n'],1)
        finally:conn.close()

    def test_stale_status_assignment_and_handover_cannot_overwrite(self):
        for field,value in [('expected_status','Testing'),('expected_tech_id','12'),('expected_handover','shipped')]:
            with self.subTest(field=field):
                status,_,_=self.update(101,**{field:value,'status':'Diagnosing'})
                self.assertEqual(status,409)
                self.assertEqual(self.ticket(101)['status'],'New')

    def test_rejects_invalid_status_and_cross_center_inactive_nontech_assignment(self):
        for change in [{'status':'invented'},{'assigned_tech_id':'not-a-number'},
                       {'assigned_tech_id':31},{'assigned_tech_id':14},{'assigned_tech_id':21}]:
            with self.subTest(change=change):
                self.assertEqual(self.update(101,**change)[0],400)
                self.assertEqual(self.ticket(101)['status'],'New')

    def test_manager_update_cross_center_and_missing_csrf_blocked(self):
        params={'status':'Testing','assigned_tech_id':31}
        self.assertEqual(self.request('/admin/ticket/108/update',method='POST',user_id=21,fields=params)[0],403)
        self.assertEqual(self.request('/admin/ticket/101/update',method='POST',fields={'status':'Diagnosing'},csrf=False)[0],403)
        self.assertEqual(self.ticket(101)['status'],'New')

    def test_closing_sets_pending_then_shipping_or_collection_clears_queue(self):
        self.assertEqual(self.update(101,status='Resolved/Closed')[0],302)
        self.assertEqual(self.ticket(101)['handover_status'],'pending')
        self.assertTrue(self.ticket(101)['closed_at'])
        self.assertEqual(self.update(101,handover_status='shipped')[0],302)
        self.assertEqual(self.ticket(101)['handover_status'],'shipped')
        self.assertTrue(self.ticket(101)['handover_at'])
        self.assertEqual(self.update(105,handover_status='collected')[0],302)
        self.assertEqual(self.ticket(105)['handover_status'],'collected')

    def test_cannot_deliver_open_ticket_and_reopening_clears_delivery(self):
        self.assertEqual(self.update(101,handover_status='shipped')[0],400)
        self.assertEqual(self.update(101,handover_status='invalid')[0],400)
        self.assertEqual(self.update(105,handover_status='pending')[0],302)
        self.assertEqual(self.update(105,status='In Repair',handover_status='unrecorded')[0],302)
        ticket=self.ticket(105)
        self.assertIsNone(ticket['closed_at'])
        self.assertIsNone(ticket['handover_at'])
        self.assertEqual(ticket['handover_status'],'unrecorded')

    def test_old_closed_jobs_remain_unknown_until_explicitly_classified(self):
        self.assertEqual(self.ticket(105)['handover_status'],'unrecorded')
        self.assertEqual(self.update(105,handover_status='pending')[0],302)
        self.assertEqual(self.ticket(105)['handover_status'],'pending')
        self.assertEqual(self.ticket(106)['handover_status'],'unrecorded')

    def test_external_return_url_is_refused(self):
        status,headers,_=self.update(101,status='Diagnosing',next='https://example.invalid/')
        self.assertEqual(status,302)
        self.assertEqual(headers['Location'],'/admin/board')

    def customer_fixture(self):
        self.mutate('UPDATE Users SET customer_id=1 WHERE user_id=20')
        self.mutate("INSERT INTO Customers (customer_id,name,phone) VALUES (2,'OTHER_PRIVATE_CUSTOMER','OTHER_PRIVATE_PHONE')")
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active,customer_id) VALUES (22,'other-fictional','private-fake-password','customer','OTHER_PRIVATE_USER',1,2)")
        self.mutate("INSERT INTO Devices (device_sn,customer_id,model) VALUES ('OTHER-PRIVATE-SN',2,'OTHER_PRIVATE_MODEL')")
        self.mutate("INSERT INTO Devices (device_sn,customer_id,model) VALUES ('OWN-NO-JOB',1,'Own Idle Printer')")
        self.mutate("INSERT INTO Tickets (ticket_id,device_sn,status,created_at,description,center_id) VALUES (201,'OTHER-PRIVATE-SN','In Repair','2026-10-22 08:00:00','OTHER_PRIVATE_DESCRIPTION',1)")
        self.mutate("UPDATE Ticket_Status_History SET note='INTERNAL_NOTE_MUST_NOT_LEAK' WHERE ticket_id=102")

    def test_customer_map_only_contains_own_latest_jobs_and_devices(self):
        self.customer_fixture()
        status,_,html=self.request('/customer/office',user_id=20)
        self.assertEqual(status,200)
        payload=self.payload(html)
        self.assertTrue(payload['readOnly'])
        self.assertEqual(len(payload['tickets']),4)
        self.assertEqual(len(payload['devices']),5)
        self.assertEqual({t['ticket_id'] for t in payload['tickets']},{108,109,110,107})
        self.assertEqual(payload['techs'],[])
        for private in ['OTHER_PRIVATE','OTHER-PRIVATE','INTERNAL_NOTE_MUST_NOT_LEAK',
                        'SENTINEL_PHONE','SENTINEL_LOGIN','pbkdf2$fake','Other Branch Tech']:
            self.assertNotIn(private,html)
        self.assertTrue(all(t['assigned_tech_id'] is None for t in payload['tickets']))
        self.assertNotIn('id="office-update-form"',html)
        self.assertNotIn('id="office-edit-status"',html)
        self.assertNotIn('id="office-save"',html)
        self.assertIn('Virtual Office ของฉัน',html)

    def test_customer_params_cannot_change_owner_scope(self):
        self.customer_fixture()
        status,_,html=self.request('/customer/office',user_id=20,
                                  query='customer_id=2&user_id=22&center_id=2&device_sn=OTHER-PRIVATE-SN')
        self.assertEqual(status,200)
        self.assertNotIn('OTHER_PRIVATE',html)
        self.assertNotIn('OTHER-PRIVATE-SN',html)
        other=self.payload(self.request('/customer/office',user_id=22)[2])
        self.assertEqual([t['ticket_id'] for t in other['tickets']],[201])
        self.assertEqual([d['sn'] for d in other['devices']],['OTHER-PRIVATE-SN'])

    def test_customer_map_keeps_old_open_job_and_does_not_invent_location_for_idle_device(self):
        self.customer_fixture()
        self.mutate("UPDATE Tickets SET created_at='2020-01-01 10:00:00' WHERE device_sn='FAKE-SN-0004'")
        payload=self.payload(self.request('/customer/office',user_id=20,query='from=2026-10-01&to=2026-10-31')[2])
        self.assertIn(108,[t['ticket_id'] for t in payload['tickets']])
        idle=next(d for d in payload['devices'] if d['sn']=='OWN-NO-JOB')
        self.assertFalse(idle['has_ticket'])
        self.assertEqual(idle['label'],'ยังไม่มีงานซ่อม')
        self.assertNotIn('OWN-NO-JOB',[t['device_sn'] for t in payload['tickets']])

    def test_customer_history_contains_no_internal_notes_or_staff_identity(self):
        self.customer_fixture()
        self.mutate("UPDATE Tickets SET created_at='2026-10-23 10:00:00' WHERE ticket_id=102")
        payload=self.payload(self.request('/customer/office',user_id=20)[2])
        ticket=next(t for t in payload['tickets'] if t['ticket_id']==102)
        self.assertEqual(len(ticket['history']),1)
        self.assertEqual(ticket['history'][0]['status'],app.db.STATUS_LABELS['In Repair'])
        self.assertEqual(ticket['history'][0]['note'],'')
        self.assertEqual(ticket['history'][0]['by'],'')

    def test_empty_customer_and_missing_customer_binding_fail_closed(self):
        status,_,html=self.request('/customer/office',user_id=20)
        self.assertEqual(status,200)
        self.assertEqual(self.payload(html)['tickets'],[])
        self.assertEqual(self.payload(html)['devices'],[])
        self.assertIn('ยังไม่มีเครื่องพิมพ์ในบัญชีนี้',html)

    def test_customer_map_role_and_write_protection(self):
        self.customer_fixture()
        for uid in (99,21,11):
            self.assertEqual(self.request('/customer/office',user_id=uid)[0],403)
        self.assertEqual(self.request('/customer/office',user_id=999)[0],302)
        self.assertEqual(self.request('/customer/office',method='POST',user_id=20,fields={'status':'Testing'})[0],404)
        self.assertEqual(self.request('/admin/ticket/102/update',method='POST',user_id=20,
                                      fields={'status':'Testing','assigned_tech_id':11})[0],403)
        self.assertEqual(self.ticket(102)['status'],'In Repair')
