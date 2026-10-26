"""Explicitly opt-in, fictional local test stack only; see docs/odoo-local-test.md."""
import os
if os.environ.get("TDSP_LOCAL_TEST") != "1":
    raise SystemExit("Refusing to run outside the isolated local test stack")
import db,os
c=db.get_conn()
admin=c.execute('SELECT user_id FROM Users WHERE username=?',(os.environ['INITIAL_ADMIN_USERNAME'],)).fetchone()['user_id']
center=c.execute("SELECT center_id FROM Service_Centers WHERE name=?",('DEMO Local Test Service Center',)).fetchone()
if not center:
 center_id=c.execute("INSERT INTO Service_Centers(name,address,phone,sells_products,is_headquarters) VALUES(?,?,?,1,0)",('DEMO Local Test Service Center','Fictional address for integration test','0000000000')).lastrowid
else:center_id=center['center_id']
customer=c.execute("SELECT customer_id FROM Customers WHERE name=?",('DEMO Local Test Customer',)).fetchone()
customer_id=customer['customer_id'] if customer else c.execute("INSERT INTO Customers(name,phone,email) VALUES(?,?,?)",('DEMO Local Test Customer','0000000000','test@example.invalid')).lastrowid
if not c.execute("SELECT part_sku FROM Spare_Parts WHERE part_sku='DEMO-LOCAL-PART'").fetchone():
 c.execute("INSERT INTO Spare_Parts(part_sku,part_name,stock_quantity,cost_price,center_id) VALUES(?,?,?,?,?)",('DEMO-LOCAL-PART','DEMO Nozzle / หัวฉีดจำลองสำหรับทดสอบเท่านั้น',100,125.5,center_id))
if not c.execute("SELECT order_id FROM Sales_Orders WHERE notes='DEMO Local Odoo Test'").fetchone():
 oid=c.execute("INSERT INTO Sales_Orders(center_id,sold_by,customer_id,created_at,notes) VALUES(?,?,?,?,?)",(center_id,admin,customer_id,db.now(),'DEMO Local Odoo Test')).lastrowid
 c.execute('INSERT INTO Sale_Items(order_id,part_sku,quantity,unit_price) VALUES(?,?,?,?)',(oid,'DEMO-LOCAL-PART',2,125.5))
if not c.execute("SELECT order_id FROM Restock_Orders WHERE notes='DEMO Local Odoo Test'").fetchone():
 for i in range(12):
  oid=c.execute("INSERT INTO Restock_Orders(center_id,requested_by,created_at,notes,tracking_number) VALUES(?,?,?,?,?)",(center_id,admin,db.now(),'DEMO Local Odoo Test' if i==0 else 'DEMO Scroll Test '+str(i),'DEMO-TRACK-0000000'+str(i))).lastrowid
  c.execute('INSERT INTO Restock_Order_Items(order_id,part_sku,quantity_requested,unit_price) VALUES(?,?,?,?)',(oid,'DEMO-LOCAL-PART',3+i,125.5))
c.commit();c.close();print('Fictional sale and service-center order fixtures ready; no source/production data imported.')
