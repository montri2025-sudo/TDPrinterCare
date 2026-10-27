import os
if os.environ.get('TDSP_LOCAL_TEST')!='1': raise SystemExit('Local test only')
import db
c=db.get_conn()
center=c.execute("SELECT center_id FROM Service_Centers WHERE name='DEMO Local Test Service Center'").fetchone()['center_id']
customer=c.execute("SELECT customer_id FROM Customers WHERE name='DEMO Local Test Customer'").fetchone()['customer_id']
if not c.execute("SELECT user_id FROM Users WHERE username='fs-local-technician'").fetchone():
 c.execute('INSERT INTO Users(username,password,role,name,center_id) VALUES(?,?,?,?,?)',('fs-local-technician',db.hash_password(os.urandom(24).hex()),'technician','ช่างทดสอบบริการนอกสถานที่',center))
if not c.execute("SELECT device_sn FROM Devices WHERE device_sn='LOCAL-FS-TEST-001'").fetchone():
 c.execute('INSERT INTO Devices(device_sn,customer_id,model,type) VALUES(?,?,?,?)',('LOCAL-FS-TEST-001',customer,'FDM เครื่องทดสอบหน้างาน','FDM'))
c.execute('UPDATE Service_Centers SET latitude=?,longitude=? WHERE center_id=?',(13.827,100.668,center))
c.commit();c.close()
print('Isolated local fixtures ready; no production or Odoo changes.')
