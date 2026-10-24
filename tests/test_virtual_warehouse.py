"""Warehouse planning and read-only staff-room checks with fictional SQLite data."""
import datetime
import json
import re
import test_integration_api as fixtures
import test_virtual_office as office
import app


class TestVirtualWarehouse(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp();self.tokens=[]
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (99,'fictional-admin','fictional','admin','Fiction Admin',1)")
        self.mutate("INSERT INTO Spare_Parts (part_sku,part_name,stock_quantity,reorder_level,center_id,storage_location,cost_price) VALUES ('STOCK-A','Fiction Nozzle',2,5,1,'A01',123456.78)")
        self.mutate("INSERT INTO Spare_Parts (part_sku,part_name,stock_quantity,reorder_level,center_id,storage_location) VALUES ('STOCK-B','PRIVATE_BRANCH_B_PRODUCT',1,2,2,'PRIVATE-B-RACK')")
        for oid,center,cancelled,qty,sku in [(501,1,None,30,'STOCK-A'),(502,1,'2026-10-22 00:00:00',999,'STOCK-A'),(503,2,None,200,'STOCK-B'),(504,2,None,100,'STOCK-A')]:
            self.mutate('INSERT INTO Sales_Orders (order_id,center_id,sold_by,created_at,cancelled_at) VALUES (?,?,11,?,?)',(oid,center,'2026-10-15 10:00:00',cancelled))
            self.mutate('INSERT INTO Sale_Items (item_id,order_id,part_sku,quantity,unit_price) VALUES (?,?,?,?,1)',(oid,oid,sku,qty))
        for log_id,state,qty in [(601,'auto',10),(602,'approved',5),(603,'pending',100),(604,'rejected',999)]:
            self.mutate('INSERT INTO Service_Logs (log_id,ticket_id,part_sku_used,quantity_used,approval_status,created_at) VALUES (?,102,?,?,?,?)',(log_id,'STOCK-A',qty,state,'2026-10-20 10:00:00'))
        for oid,state,qty,received in [(701,'processing',10,2),(702,'requested',100,0),(703,'received',500,500),(704,'cancelled',999,0)]:
            self.mutate('INSERT INTO Restock_Orders (order_id,center_id,requested_by,status,created_at) VALUES (?,1,21,?,?)',(oid,state,'2026-10-20 10:00:00'))
            self.mutate('INSERT INTO Restock_Order_Items (item_id,order_id,part_sku,quantity_requested,quantity_received) VALUES (?,?,?,?,?)',(oid,oid,'STOCK-A',qty,received))

    def tearDown(self):
        for token in self.tokens:app.SESSIONS.pop(token,None)
        super().tearDown()

    def context(self, user, today=datetime.date(2026,10,24)):
        conn=office.OfficeConn(self.path)
        try:
            parts=app._load_parts(conn,center_id=user.get('center_id') if user['role']!='admin' else None)
            return app._warehouse_insights(conn,user,parts,today=today)
        finally:conn.close()

    def payload(self, html):
        return json.loads(re.search(r'id="warehouse-data">(.*?)</script>',html,re.S).group(1))

    def request(self,path='/staff/warehouse',**kwargs):
        return office.TestVirtualOffice.request(self,path,**kwargs)

    def test_reorder_uses_actual_sales_approved_usage_days_and_buffer(self):
        data=self.context({'role':'manager','center_id':1})
        p=next(p for p in data['products'] if p['sku']=='STOCK-A')
        self.assertEqual(data['remainingDays'],8)
        self.assertEqual(p['soldMonth'],30)
        self.assertEqual(p['used30'],45)
        self.assertEqual(p['forecast'],12)
        self.assertEqual(p['suggested'],15)
        self.assertEqual(p['incoming'],8)  # displayed separately; no assumed arrival date
        self.assertTrue(p['low']);self.assertTrue(p['bestSeller'])
        self.assertNotIn('STOCK-B',[p['sku'] for p in data['products']])

    def test_admin_and_manager_keep_distinct_transaction_scope(self):
        admin=next(p for p in self.context({'role':'admin'})['products'] if p['sku']=='STOCK-A')
        self.assertEqual(admin['soldMonth'],130)
        self.assertFalse(admin['bestSeller'])  # STOCK-B sold 200; cutoff is across all visible sellers
        manager=next(p for p in self.context({'role':'manager','center_id':1})['products'] if p['sku']=='STOCK-A')
        self.assertEqual(manager['soldMonth'],30)
        self.assertTrue(manager['bestSeller'])

    def test_no_history_uses_threshold_not_invented_sales_and_last_day_is_one(self):
        data=self.context({'role':'manager','center_id':1},today=datetime.date(2026,10,31))
        self.assertEqual(data['remainingDays'],1)
        p=next(p for p in data['products'] if p['sku']=='FAKE-SKU-1')
        self.assertEqual(p['soldMonth'],0);self.assertEqual(p['forecast'],0)
        self.assertFalse(p['bestSeller']);self.assertEqual(p['suggested'],0)
        self.mutate("UPDATE Spare_Parts SET stock_quantity=5 WHERE part_sku='STOCK-A'")
        future=self.context({'role':'manager','center_id':1},today=datetime.date(2027,1,1))
        p=next(p for p in future['products'] if p['sku']=='STOCK-A')
        self.assertEqual(p['suggested'],1)  # above the configured reorder trigger
        self.assertEqual(p['forecast'],0)

    def test_staff_room_contains_racks_summary_screens_and_no_cost_or_stock_forms(self):
        status,_,html=self.request(user_id=11)
        self.assertEqual(status,200)
        data=self.payload(html)
        self.assertTrue(data['readOnly'])
        self.assertIn('ห้องมอนิเตอร์คลังสินค้า',html)
        self.assertIn('warehouse-screen-stock',html)
        self.assertIn('warehouse-screen-rows',html)
        self.assertIn('warehouse-racks',html)
        for secret in ['PRIVATE_BRANCH_B_PRODUCT','PRIVATE-B-RACK','123456.78','cost_price','name="qty"','action="/admin/inventory']:
            self.assertNotIn(secret,html)
        self.assertNotIn('STOCK-B',[p['sku'] for p in data['products']])
        self.assertNotIn('id="warehouse-product-detail"',html)

    def test_staff_room_denies_customer_and_unbound_staff_sees_nothing(self):
        self.assertEqual(self.request(user_id=20)[0],403)
        self.assertEqual(self.request(user_id=999)[0],302)
        status,_,html=self.request(user_id=41)
        self.assertEqual(status,200)
        self.assertEqual(self.payload(html)['products'],[])
        self.assertEqual(self.request(method='POST',user_id=11,fields={'qty':999})[0],404)

    def test_inventory_room_preserves_management_tools_and_safe_product_json(self):
        self.mutate('UPDATE Spare_Parts SET part_name=? WHERE part_sku=?',('</script><img src=x onerror="bad">','STOCK-A'))
        status,_,html=self.request('/admin/inventory',user_id=99,query='')
        self.assertEqual(status,200)
        self.assertIn('warehouse-tools',html)
        self.assertIn('action="/admin/inventory/new"',html)
        self.assertNotIn('</script><img src=x onerror="bad">',html)
        self.assertEqual(next(p for p in self.payload(html)['products'] if p['sku']=='STOCK-A')['name'],'</script><img src=x onerror="bad">')
