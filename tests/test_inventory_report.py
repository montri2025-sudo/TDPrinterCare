"""All-product print reports preserve branch scope and show current cost values."""
from test_virtual_warehouse import TestVirtualWarehouse

class TestInventoryReport(TestVirtualWarehouse):
    def test_admin_report_contains_all_stock_even_with_search_parameter(self):
        self.mutate("UPDATE Spare_Parts SET cost_price=12.34 WHERE part_sku='STOCK-A'")
        status,_,html=self.request('/admin/inventory/report',query='q=does-not-exist')
        self.assertEqual(status,200)
        self.assertIn('PRIVATE_BRANCH_B_PRODUCT',html)
        self.assertIn('Fiction Nozzle',html)
        self.assertIn('24.68',html)
        self.assertIn('ราคาทุน',html)
        self.assertIn('thead{display:table-header-group}',html)

    def test_branch_report_and_unbound_manager_cannot_leak_other_branches(self):
        status,_,html=self.request('/admin/inventory/report',user_id=21,query='center_id=2')
        self.assertEqual(status,200)
        self.assertIn('Fiction Nozzle',html)
        self.assertNotIn('PRIVATE_BRANCH_B_PRODUCT',html)
        self.mutate('UPDATE Users SET center_id=NULL WHERE user_id=21')
        status,_,html=self.request('/admin/inventory/report',user_id=21)
        self.assertEqual(status,200)
        self.assertNotIn('Fiction Nozzle',html)
        self.assertIn('ไม่มีสินค้า',html)

    def test_cost_report_is_not_accessible_to_customer_sales_or_technician(self):
        for uid in [20,11,12]:
            self.assertEqual(self.request('/admin/inventory/report',user_id=uid)[0],403)
