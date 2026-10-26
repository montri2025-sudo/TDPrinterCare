"""Explicitly opt-in, fictional local test stack only; see docs/odoo-local-test.md."""
import os
if os.environ.get("TDSP_LOCAL_TEST") != "1":
    raise SystemExit("Refusing to run outside the isolated local test stack")
import os,re,json,urllib.request,urllib.parse,urllib.error,http.cookiejar,xmlrpc.client
jar=http.cookiejar.CookieJar();http=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def get(path):return http.open('http://127.0.0.1:8000'+path).read().decode()
def post(path,fields):
 request=urllib.request.Request('http://127.0.0.1:8000'+path,data=urllib.parse.urlencode(fields).encode())
 try:
  response=http.open(request);return response.status,response.read().decode()
 except urllib.error.HTTPError as error:return error.code,error.read().decode()
def token(html):return re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
page=get('/login');csrf=token(page)
status,page=post('/login',{'csrf_token':csrf,'username':os.environ['INITIAL_ADMIN_USERNAME'],'password':os.environ['INITIAL_ADMIN_PASSWORD']})
assert status==200 and 'ออกจากระบบ' in page,'app login failed'
csrf=token(get('/sales/order/1'))
url=os.environ['ODOO_URL'];database=os.environ['ODOO_DB'];key=os.environ['ODOO_API_KEY']
uid=xmlrpc.client.ServerProxy(url+'/xmlrpc/2/common').authenticate(database,os.environ['ODOO_USERNAME'],key,{})
assert uid,'Odoo authentication failed'
proxy=xmlrpc.client.ServerProxy(url+'/xmlrpc/2/object')
def rpc(model,method,args,kw=None):return proxy.execute_kw(database,uid,key,model,method,args,kw or {})
# Demonstrate the currency guard before changing this disposable test pricelist.
price=rpc('product.pricelist','read',[[1]],{'fields':['currency_id']})[0]
currency=rpc('res.currency','read',[[price['currency_id'][0]]],{'fields':['name']})[0]['name']
if currency!='THB':
 status,body=post('/sales/order/1/odoo-quotation',{'csrf_token':csrf})
 assert status==502 and 'THB' in body,'foreign-currency guard failed'
 print('PASS: wrong currency rejected before quotation creation')
 thb=rpc('res.currency','search',[[['name','=','THB']]])[0]
 rpc('product.pricelist','write',[[1],{'currency_id':thb}])
counts={model:rpc(model,'search_count',[[]]) for model in ['stock.move','account.move']}
for kind,path,total in [('SALE','/sales/order/1/odoo-quotation',251.0),('RESTOCK','/admin/restock-orders/1/odoo-quotation',376.5)]:
 for attempt in range(2):
  status,body=post(path,{'csrf_token':csrf})
  if status!=200:
   print('FAILED route',kind,'HTTP',status,re.sub('<[^>]+>',' ',body)[-400:]);raise AssertionError('export failed')
 records=rpc('sale.order','search_read',[[['client_order_ref','=',f'TDSP-{kind}-1']]],{'fields':['name','state','amount_total','order_line']})
 assert len(records)==1 and records[0]['state']=='draft' and abs(records[0]['amount_total']-total)<.001,records
 print('PASS:',kind,'created one draft, repeated export reused; THB total',records[0]['amount_total'])
assert counts=={model:rpc(model,'search_count',[[]]) for model in counts},'unexpected stock or invoice activity'
print('PASS: no invoice or stock move created by quotation exports')
# Prototype only: inspect actual Odoo Repair workflow with a fictitious serial-numbered machine.
partner=rpc('res.partner','search',[[['ref','=','TDSP-CUST-1']]])[0]
products=rpc('product.template','search',[[['default_code','=','TDSP-DEMO-MACHINE']]])
if products:template=products[0]
else:template=rpc('product.template','create',[{'name':'DEMO repair machine / เครื่องจำลอง','default_code':'TDSP-DEMO-MACHINE','type':'consu','is_storable':True,'tracking':'serial'}])
product=rpc('product.template','read',[[template]],{'fields':['product_variant_id']})[0]['product_variant_id'][0]
lots=rpc('stock.lot','search',[[['name','=','TDSP-DEMO-SN-001'],['product_id','=',product]]])
lot=lots[0] if lots else rpc('stock.lot','create',[{'name':'TDSP-DEMO-SN-001','product_id':product}])
repairs=rpc('repair.order','search',[[['name','=','TDSP-REPAIR-DEMO-1']]])
repair=repairs[0] if repairs else rpc('repair.order','create',[{'name':'TDSP-REPAIR-DEMO-1','partner_id':partner,'product_id':product,'lot_id':lot,'product_qty':1,'internal_notes':'<p>TDPrinterCare fictional repair prototype. Source status: Diagnosing. No automatic state transition.</p>'}])
record=rpc('repair.order','read',[[repair]],{'fields':['name','state','product_id','lot_id','partner_id','move_ids','sale_order_id']})[0]
assert record['state']=='draft' and record['lot_id'][0]==lot and not record['move_ids'] and not record['sale_order_id'],record
assert counts=={model:rpc(model,'search_count',[[]]) for model in counts}
print('PASS: Repair prototype stores customer, product and serial; state=draft; no stock move or quotation generated automatically')
print('ALL LOCAL ODOO INTEGRATION CHECKS PASSED')
