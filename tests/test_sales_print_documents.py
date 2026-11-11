"""Sales invoice and print layout checks using an isolated sale."""
import test_virtual_office as office


class TestSalesPrintDocuments(office.fixtures.ApiTestCase):
    request = office.TestVirtualOffice.request

    def setUp(self):
        super().setUp()
        self.tokens = []
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active) VALUES(99,'print-admin','fake','admin','Print Admin',1)")
        self.mutate("INSERT INTO Sales_Orders(order_id,center_id,sold_by,customer_id,created_at) VALUES(1,1,99,1,'2026-11-11')")
        self.mutate("INSERT INTO Sale_Items(order_id,part_sku,quantity,unit_price) VALUES(1,'FAKE-SKU-1',2,100)")

    def tearDown(self):
        for token in self.tokens:
            office.app.SESSIONS.pop(token, None)
        super().tearDown()

    def test_unpaid_invoice_prints_with_optional_vat_and_does_not_confirm_payment(self):
        before = self.request('/sales/order/1')[2]
        self.assertIn('/sales/order/1/invoice/print', before)
        status, _, html = self.request('/sales/order/1/invoice/print', query='vat=1')
        self.assertEqual(status, 200)
        self.assertIn('INV-S000001', html)
        self.assertIn('214.00 บาท', html)
        self.assertIn('ไม่ใช่การยืนยันรับชำระเงิน', html)
        self.assertEqual(self.request('/sales/order/1/tax-invoice/print')[0], 404)
        self.assertIn('ยังไม่ได้ยืนยันรับชำระเงิน', self.request('/sales/order/1')[2])
        self.assertIn('200.00 บาท', self.request('/sales/order/1/invoice/print', query='')[2])

    def test_invoice_rejects_other_branch_customer_and_cancelled_order(self):
        path = '/sales/order/1/invoice/print'
        self.assertEqual(self.request(path, user_id=20)[0], 403)
        self.mutate('UPDATE Sales_Orders SET center_id=2')
        self.assertEqual(self.request(path, user_id=21)[0], 403)
        self.mutate("UPDATE Sales_Orders SET cancelled_at='2026-11-11'")
        self.assertEqual(self.request(path)[0], 404)

    def test_paid_invoice_and_tax_invoice_use_same_vat_and_shared_a4_layout(self):
        self.mutate("UPDATE Sales_Orders SET payment_confirmed_at='2026-11-11', payment_doc_type='tax_invoice'")
        for kind in ('invoice', 'quote', 'tax-invoice'):
            with self.subTest(kind=kind):
                status, _, html = self.request(f'/sales/order/1/{kind}/print', query='')
                self.assertEqual(status, 200)
                self.assertIn('size: A4 portrait; margin: 16mm 12mm 14mm', html)
                self.assertIn('<thead>', html)
                self.assertIn('class="header"', html)
                self.assertIn('200.00' if kind == 'quote' else '214.00', html)
