"""Draft-only Odoo export; fake RPCs never contact a real server."""
import unittest
from unittest.mock import patch
import xmlrpc.client
import test_virtual_office as office
import odoo_client as client

class FakeRPC:
    def __init__(self):self.calls=[];self.orders=[];self.currency='THB';self.variants=[9]
    def execute_kw(self,db,uid,key,model,method,args,kwargs=None):
        self.calls.append((model,method,args,kwargs))
        if model=='res.users':return [{'company_id':[1,'Test']}]
        if model=='sale.order' and method=='search_read':return [o for o in self.orders if o['ref']==args[0][0][2]]
        if model=='res.partner':return [{'property_product_pricelist':[1,'THB']}]
        if model=='product.pricelist':return [{'currency_id':[1,'Currency']}]
        if model=='res.currency':return [{'name':self.currency}]
        if model=='sale.order.line':return {'tax_ids':{'type':'many2many'}}
        if model=='product.product':return self.variants
        if model=='sale.order' and method=='create':
            values=args[0];self.orders.append({'id':len(self.orders)+1,'name':'S-TEST','state':'draft','note':values['note'],'ref':values['client_order_ref']});return len(self.orders)
        if model=='sale.order' and method=='read':return [self.orders[args[0][0]-1]]
        raise AssertionError((model,method))

class TestOdooQuotation(unittest.TestCase):
    def setUp(self):
        self.rpc=FakeRPC();self.patches=[patch.object(client,'_is_configured',return_value=True),patch.object(client,'_authenticate',return_value=1),patch.object(client,'_make_proxy',return_value=self.rpc)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.lines=[{'template_id':1,'name':'Fiction Part','quantity':2,'unit_price':25.5}]
    def test_creates_only_draft_and_repeat_reuses_without_write_or_confirmation(self):
        first=client.sync_quotation('sale',1,3,self.lines,notes='<test>');second=client.sync_quotation('sale',1,3,self.lines,notes='<test>')
        self.assertEqual(first['id'],second['id']);self.assertTrue(second['reused']);self.assertFalse(second['source_changed'])
        self.assertEqual(len(self.rpc.orders),1)
        self.assertFalse(any(c[1] in ('write','action_confirm','action_create_invoice','action_quotation_send') for c in self.rpc.calls))
        values=next(c[2][0] for c in self.rpc.calls if c[:2]==('sale.order','create'))
        self.assertEqual(values['order_line'][0][2]['tax_ids'],[(5,0,0)])
        self.assertIn('&lt;test&gt;',values['note'])
    def test_changed_source_is_reported_without_overwriting_odoo(self):
        client.sync_quotation('sale',1,3,self.lines);self.lines[0]['unit_price']=30
        result=client.sync_quotation('sale',1,3,self.lines);self.assertTrue(result['source_changed']);self.assertEqual(len(self.rpc.orders),1)
    def test_sales_and_restock_references_cannot_collide(self):
        a=client.sync_quotation('sale',1,3,self.lines);b=client.sync_quotation('restock',1,3,self.lines)
        self.assertNotEqual(a['id'],b['id']);self.assertNotEqual(a['reference'],b['reference'])
    def test_wrong_currency_and_ambiguous_variants_do_not_create_quote(self):
        self.rpc.currency='USD'
        with self.assertRaises(client.OdooQuotationError):client.sync_quotation('sale',1,3,self.lines)
        self.rpc.currency='THB';self.rpc.variants=[9,10]
        with self.assertRaises(client.OdooQuotationError):client.sync_quotation('sale',1,3,self.lines)
        self.assertEqual(self.rpc.orders,[])
    def test_invalid_numeric_values_fail_before_rpc(self):
        for value in [0,-1,float('nan'),float('inf')]:
            self.lines[0]['quantity']=value
            with self.assertRaises(client.OdooQuotationError):client.sync_quotation('sale',1,3,self.lines)
        self.assertEqual(self.rpc.calls,[])
    def test_remote_fault_does_not_expose_secret_detail(self):
        self.rpc.execute_kw=lambda *a,**k:(_ for _ in ()).throw(xmlrpc.client.Fault(1,'PRIVATE_DETAIL'))
        with self.assertRaises(client.OdooQuotationError) as result:client.sync_quotation('sale',1,3,self.lines)
        self.assertNotIn('PRIVATE_DETAIL',str(result.exception))

class TestOdooTransport(unittest.TestCase):
    def test_https_uses_safe_transport_with_timeout(self):
        with patch.object(client.db,'ODOO_URL','https://odoo.invalid'),patch.object(client.xmlrpc.client,'ServerProxy') as proxy:
            client._make_proxy('/xmlrpc/2/common')
        self.assertIsInstance(proxy.call_args.kwargs['transport'],xmlrpc.client.SafeTransport)

class LockedTestConn(office.OfficeConn):
    def execute(self,sql,params=()):return super().execute(sql.replace(' FOR UPDATE',''),params)

class TestOdooOrderRoutes(office.fixtures.ApiTestCase):
    request=office.TestVirtualOffice.request
    def setUp(self):
        super().setUp();self.tokens=[]
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active) VALUES(99,'test-admin','fake','admin','Test Admin',1)")
        self.mutate("INSERT INTO Sales_Orders(order_id,center_id,sold_by,customer_id,created_at) VALUES(1,1,99,1,'2026-10-26')")
        self.mutate("INSERT INTO Sale_Items(order_id,part_sku,quantity,unit_price) VALUES(1,'FAKE-SKU-1',2,25)")
        self.mutate("INSERT INTO Restock_Orders(order_id,center_id,requested_by,created_at) VALUES(1,1,21,'2026-10-26')")
        self.mutate("INSERT INTO Restock_Order_Items(order_id,part_sku,quantity_requested,unit_price) VALUES(1,'FAKE-SKU-1',3,20)")
        p=patch.object(office,'OfficeConn',LockedTestConn);p.start();self.addCleanup(p.stop)
    def tearDown(self):
        for token in self.tokens:office.app.SESSIONS.pop(token,None)
        super().tearDown()
    def test_csrf_roles_and_branch_isolation_block_export(self):
        with patch.object(client,'sync_quotation') as send:
            self.assertEqual(self.request('/sales/order/1/odoo-quotation',method='POST',csrf=False)[0],403)
            self.assertEqual(self.request('/sales/order/1/odoo-quotation',user_id=20,method='POST')[0],403)
            self.assertEqual(self.request('/admin/restock-orders/1/odoo-quotation',user_id=21,method='POST')[0],403)
            self.mutate("UPDATE Sales_Orders SET center_id=2 WHERE order_id=1")
            self.assertEqual(self.request('/sales/order/1/odoo-quotation',user_id=21,method='POST')[0],403)
            send.assert_not_called()
    def test_canceled_order_and_missing_customer_block_before_rpc(self):
        with patch.object(client,'_is_configured',return_value=True),patch.object(client,'sync_customer') as partner:
            self.mutate("UPDATE Sales_Orders SET cancelled_at='2026-10-26' WHERE order_id=1")
            self.assertEqual(self.request('/sales/order/1/odoo-quotation',method='POST')[0],400)
            self.mutate("UPDATE Sales_Orders SET cancelled_at=NULL,customer_id=NULL WHERE order_id=1")
            self.assertEqual(self.request('/sales/order/1/odoo-quotation',method='POST')[0],400);partner.assert_not_called()
    def test_success_and_remote_failure_use_actual_result(self):
        result={'id':1,'name':'S-TEST','reference':'TDSP-SALE-1','state':'draft','reused':False,'source_changed':False}
        with patch.object(client,'_is_configured',return_value=True),patch.object(client,'sync_customer',return_value=3),patch.object(client,'resolve_quotation_product',return_value=4),patch.object(client,'sync_quotation',return_value=result) as send:
            status,_,html=self.request('/sales/order/1/odoo-quotation',method='POST');self.assertEqual(status,200);self.assertIn('S-TEST',html);self.assertEqual(send.call_args.args[3][0]['quantity'],2)
            send.side_effect=client.OdooQuotationError('Test failure');self.assertEqual(self.request('/sales/order/1/odoo-quotation',method='POST')[0],502)
