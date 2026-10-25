"""Customer virtual factory: owner isolation and real maintenance state."""
import json
import re
from unittest.mock import patch
import test_integration_api as fixtures
import test_virtual_office as office
import app


class TestCustomerFactory(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp();self.tokens=[]
        self.mutate('UPDATE Users SET customer_id=1 WHERE user_id=20')
        self.mutate("UPDATE Devices SET total_usage_hours=10 WHERE device_sn='FAKE-SN-0001'")
        self.mutate("INSERT INTO Maintenance_Plan_Items (plan_item_id,device_type,task_name,interval_type,interval_value,is_active,created_at) VALUES (901,'FDM','ตรวจรอบดูแลตามชั่วโมง','hours',8,1,'2026-01-01 00:00:00')")
        self.mutate("INSERT INTO Customers (customer_id,name,phone) VALUES (2,'OTHER_FACTORY_PRIVATE','PRIVATE_PHONE')")
        self.mutate("INSERT INTO Devices (device_sn,customer_id,model,type,status) VALUES ('OTHER-PRIVATE-SN',2,'OTHER_PRIVATE_FACTORY_MACHINE','FDM','Active')")

    def tearDown(self):
        for token in self.tokens:app.SESSIONS.pop(token,None)
        super().tearDown()

    def request(self, **kwargs):
        with patch.object(app,'_sync_maintenance_notifications'):
            return office.TestVirtualOffice.request(self,'/customer/dashboard',user_id=kwargs.pop('user_id',20),**kwargs)

    def payload(self,html):
        return json.loads(re.search(r'id="factory-data">(.*?)</script>',html,re.S).group(1))

    def test_factory_shows_only_own_machines_and_no_private_prices(self):
        status,_,html=self.request(query='customer_id=2&device_sn=OTHER-PRIVATE-SN')
        self.assertEqual(status,200)
        devices=self.payload(html)['devices']
        self.assertEqual(len(devices),4)
        self.assertTrue(all(d['sn'].startswith('FAKE-SN-') for d in devices))
        self.assertNotIn('OTHER_PRIVATE_FACTORY_MACHINE',html)
        self.assertNotIn('OTHER-PRIVATE-SN',html)
        self.assertNotIn('PRIVATE_PHONE',html)
        self.assertIn('Demo แนะนำหน้านี้',html)
        self.assertIn('id="factory-floor"',html)
        self.assertIn('id="customer-demo-next"',html)
        self.assertIn('ไม่ใช่การเชื่อมต่อสถานะเครื่องแบบเรียลไทม์',html)

    def test_due_maintenance_stays_visible_on_machine_in_repair(self):
        status,_,html=self.request()
        self.assertEqual(status,200)
        machine=next(d for d in self.payload(html)['devices'] if d['sn']=='FAKE-SN-0001')
        self.assertEqual(machine['status'],'in_repair')
        self.assertTrue(machine['due'])
        self.assertEqual(machine['hours'],10)
        self.assertEqual(machine['tasks'][0]['name'],'ตรวจรอบดูแลตามชั่วโมง')
        self.assertIn('maintenance-alert',html)
        self.assertIn('id="factory-blink"',html)

    def test_inactive_machines_do_not_get_maintenance_or_repair_alerts(self):
        self.mutate("UPDATE Devices SET status='Decommissioned' WHERE device_sn='FAKE-SN-0001'")
        self.mutate("UPDATE Devices SET status='Sold' WHERE device_sn='FAKE-SN-0002'")
        devices=self.payload(self.request()[2])['devices']
        inactive={d['sn']:d for d in devices if d['status'] in ('sold','decommissioned')}
        self.assertEqual(len(inactive),2)
        self.assertFalse(inactive['FAKE-SN-0001']['due'])
        self.assertEqual(inactive['FAKE-SN-0001']['tasks'],[])
        self.assertIsNone(inactive['FAKE-SN-0001']['ticketId'])

    def test_unknown_type_is_grouped_as_other_and_unsafe_names_are_text(self):
        malicious='</script><img src=x onerror="bad">'
        self.mutate('UPDATE Devices SET model=?,type=NULL WHERE device_sn=?',(malicious,'FAKE-SN-0004'))
        status,_,html=self.request()
        self.assertEqual(status,200)
        device=next(d for d in self.payload(html)['devices'] if d['sn']=='FAKE-SN-0004')
        self.assertEqual(device['type'],'Other')
        self.assertEqual(device['model'],malicious)
        self.assertNotIn(malicious,html)

    def test_no_customer_binding_is_empty_and_other_roles_are_denied(self):
        self.mutate('UPDATE Users SET customer_id=NULL WHERE user_id=20')
        status,_,html=self.request()
        self.assertEqual(status,200)
        self.assertEqual(self.payload(html)['devices'],[])
        self.assertIn('โรงงานของคุณยังไม่มีเครื่องพิมพ์',html)
        self.assertEqual(self.request(user_id=21)[0],403)
        self.assertEqual(self.request(user_id=11)[0],403)
