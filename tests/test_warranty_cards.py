"""Warranty issuance uses isolated fictional sales, never live stock."""
import sqlite3
import test_virtual_office as office
import test_integration_api as fixtures


class TestWarrantyCards(fixtures.ApiTestCase):
    request = office.TestVirtualOffice.request

    def setUp(self):
        super().setUp()
        self.tokens = []
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active) VALUES(99,'warranty-admin','fake','admin','Warranty Admin',1)")
        self.mutate("UPDATE Users SET customer_id=1 WHERE user_id=20")
        self.mutate("UPDATE Spare_Parts SET category='FDM_Printer' WHERE part_sku='FAKE-SKU-1'")
        self.mutate("INSERT INTO Sales_Orders(order_id,center_id,sold_by,customer_id,created_at,payment_confirmed_at) VALUES(1,1,99,1,'2024-02-29 10:00:00','2024-02-29 11:00:00')")
        self.mutate("UPDATE Sales_Orders SET payment_doc_type='cash_bill'")
        self.mutate("INSERT INTO Sale_Items(item_id,order_id,part_sku,quantity,unit_price) VALUES(1,1,'FAKE-SKU-1',2,100)")

    def tearDown(self):
        for token in self.tokens:
            office.app.SESSIONS.pop(token, None)
        super().tearDown()

    def issue(self, **fields):
        return self.request('/sales/order/1/warranty', method='POST', fields=dict(item_id=1, unit_number=1, serial_number='FICTION-SN-1', **fields))

    def test_issue_reprint_idempotency_customer_access_and_leap_year(self):
        self.assertEqual(self.issue()[0], 302)
        self.assertEqual(self.issue()[0], 302)
        status, _, html = self.request('/warranty/1/1/1', user_id=20)
        self.assertEqual(status, 200)
        self.assertIn('FICTION-SN-1', html)
        self.assertIn('2025-02-28', html)
        status, _, html = self.request('/customer/warranties', user_id=20)
        self.assertEqual(status, 200)
        self.assertIn('/warranty/1/1/1', html)
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM Warranty_Cards').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT stock_quantity FROM Spare_Parts').fetchone()[0], 10)
        conn.close()

    def test_blocks_unpaid_cancelled_nonprinter_and_out_of_quantity(self):
        self.mutate('UPDATE Sales_Orders SET payment_confirmed_at=NULL')
        self.assertEqual(self.issue()[0], 400)
        self.mutate("UPDATE Sales_Orders SET payment_confirmed_at='2024-02-29',cancelled_at='2024-03-01'")
        self.assertEqual(self.issue()[0], 400)
        self.mutate('UPDATE Sales_Orders SET cancelled_at=NULL')
        self.mutate("UPDATE Spare_Parts SET category='Material'")
        self.assertEqual(self.issue()[0], 400)
        self.mutate("UPDATE Spare_Parts SET category='Resin_Printer'")
        self.assertEqual(self.request('/sales/order/1/warranty', method='POST', fields={'item_id':1,'unit_number':3,'serial_number':'SN-X'})[0],400)
        self.assertEqual(self.issue()[0],302)
        self.assertIn('Resin',self.request('/warranty/1/1/1')[2])

    def test_csrf_scope_and_customer_ownership(self):
        self.assertEqual(self.request('/sales/order/1/warranty',method='POST',csrf=False)[0],403)
        self.assertEqual(self.request('/sales/order/1/warranty',method='POST',user_id=20)[0],403)
        self.issue()
        self.mutate('UPDATE Users SET center_id=2 WHERE user_id=21')
        self.assertEqual(self.request('/warranty/1/1/1',user_id=21)[0],403)
        self.mutate('UPDATE Users SET customer_id=NULL WHERE user_id=20')
        self.assertEqual(self.request('/warranty/1/1/1',user_id=20)[0],403)

    def test_duplicate_serial_does_not_create_second_card_and_snapshot_is_stable(self):
        self.issue()
        self.assertEqual(self.request('/sales/order/1/warranty',method='POST',fields={'item_id':1,'unit_number':2,'serial_number':'FICTION-SN-1'})[0],400)
        self.mutate("UPDATE Spare_Parts SET part_name='Changed Model'")
        self.assertIn('Fiction Part',self.request('/warranty/1/1/1')[2])
        self.assertEqual(self.request('/sales/order/1/warranty',method='POST',fields={'item_id':1,'unit_number':1,'serial_number':'OTHER-SN'})[0],400)

    def test_sale_detail_exposes_per_unit_form_and_escapes_serial(self):
        self.assertIn('Serial เครื่องที่ 2',self.request('/sales/order/1')[2])
        self.request('/sales/order/1/warranty',method='POST',fields={'item_id':1,'unit_number':1,'serial_number':'<script>bad</script>'})
        html=self.request('/warranty/1/1/1')[2]
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;',html)
        self.assertNotIn('<script>bad</script>',html)
