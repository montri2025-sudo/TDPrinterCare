"""Executive monitor room checks against fictional, isolated dashboard data."""
import json
import re
from unittest.mock import patch
import test_integration_api as fixtures
import test_virtual_office as office
import app


class TestMonitorRoom(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.tokens=[]
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (99,'fictional-admin','fictional','admin','Fiction Admin',1)")

    def tearDown(self):
        for token in self.tokens: app.SESSIONS.pop(token,None)
        super().tearDown()

    def request(self, **kwargs):
        # Notifications are a separate workflow; no test sends mail or touches real databases.
        with patch.object(app,'_sync_maintenance_notifications'), patch.object(app,'_maintenance_due_devices',return_value=[]):
            return office.TestVirtualOffice.request(self,'/admin/dashboard',**kwargs)

    def payload(self, html):
        return json.loads(re.search(r'id="monitor-room-data">(.*?)</script>',html,re.S).group(1))

    def test_room_reuses_actual_dashboard_counts_and_renders_six_monitors(self):
        status,_,html=self.request()
        self.assertEqual(status,200)
        data=self.payload(html)
        self.assertEqual(sum(data['statusCounts']),10)
        self.assertEqual(data['statusCounts'][0],1)
        self.assertEqual(data['statusCounts'][-1],3)
        self.assertEqual(len(data['months']),len(data['created']))
        self.assertEqual(len(data['months']),len(data['fdm']))
        self.assertEqual(len(re.findall('data-monitor="',html)),6)
        self.assertIn('id="monitor-reports"',html)
        self.assertIn('ภาพผู้บริหารเป็นภาพประกอบ',html)
        self.assertIn('ไม่อัปเดตอัตโนมัติ',html)

    def test_manager_payload_stays_in_own_branch_despite_query_parameter(self):
        status,_,html=self.request(user_id=21,query='from=2026-10-01&to=2026-10-31&center_id=2')
        self.assertEqual(status,200)
        data=self.payload(html)
        self.assertEqual(sum(data['statusCounts']),9)
        self.assertNotIn('Other Branch Tech',[w['name'] for w in data['workload']])
        self.assertIn('Test Branch A',data['scope'])

    def test_no_activity_is_encoded_as_zero_not_example_graphs(self):
        status,_,html=self.request(query='from=2000-01-01&to=2000-01-31')
        self.assertEqual(status,200)
        data=self.payload(html)
        self.assertEqual(sum(data['statusCounts']),0)
        self.assertIsNone(data['averageDays'])
        self.assertEqual(data['from'],'2000-01-01')

    def test_customer_cannot_view_business_monitor_room(self):
        self.assertEqual(self.request(user_id=20)[0],403)

    def test_suspended_technicians_are_hidden_from_current_workload(self):
        for user_id, query in [(99, ''), (99, 'center_id=1'), (21, 'center_id=2')]:
            with self.subTest(user_id=user_id, query=query):
                status, _, html = self.request(user_id=user_id, query=query)
                self.assertEqual(status, 200)
                workload = {w['name']: w['count'] for w in self.payload(html)['workload']}
                self.assertNotIn('Inactive With Job', workload)
                self.assertNotIn('Inactive No Job', workload)
                self.assertEqual(workload['Alex Tester'], 1)
                self.assertEqual(workload['Lead Tester'], 1)
                self.assertEqual(workload['Idle Tester'], 0)
                table = html.split('ภาระงานของช่าง (ตั๋วที่ยังไม่ปิด)', 1)[1].split('</table>', 1)[0]
                self.assertNotIn('Inactive With Job', table)
                self.assertNotIn('Inactive No Job', table)

    def test_suspension_updates_workload_without_deleting_tickets(self):
        self.mutate("UPDATE Users SET is_active=0 WHERE user_id=11")
        status, _, html = self.request()
        self.assertEqual(status, 200)
        self.assertNotIn('Alex Tester', [w['name'] for w in self.payload(html)['workload']])
        self.assertEqual(sum(self.payload(html)['statusCounts']), 10)
        self.mutate("UPDATE Users SET is_active=1 WHERE user_id=11")
        status, _, html = self.request()
        self.assertEqual(status, 200)
        self.assertEqual({w['name']: w['count'] for w in self.payload(html)['workload']}['Alex Tester'], 1)
