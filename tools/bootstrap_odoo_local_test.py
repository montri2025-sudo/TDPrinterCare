"""Explicitly opt-in, fictional local test stack only; see docs/odoo-local-test.md."""
import os
if os.environ.get("TDSP_LOCAL_TEST") != "1":
    raise SystemExit("Refusing to run outside the isolated local test stack")
import os,subprocess,sys
args=['--db_host=odoo-db','--db_user=odoo','--db_password='+os.environ['PASSWORD'],'--db_port=5432','--database=tdprinter_test']
result=subprocess.run(['odoo',*args,'--init=sale_management,repair','--without-demo=all','--stop-after-init','--no-http'],stdout=open('/tmp/td-test-init.log','w'),stderr=subprocess.STDOUT)
if result.returncode:
 print('Odoo test initialization failed; see /tmp/td-test-init.log inside test container');sys.exit(result.returncode)
import odoo
from odoo import api
from odoo.tools import config
from odoo.modules.registry import Registry
config.parse_config(args+['--no-http'])
with Registry('tdprinter_test').cursor() as cr:
 env=api.Environment(cr,odoo.SUPERUSER_ID,{})
 admin=env.ref('base.user_admin');admin.write({'login':'td-test-admin','password':os.environ['TEST_ODOO_ADMIN_PASSWORD']})
 thb=env.ref('base.THB');thb.active=True
 env.company.write({'currency_id':thb.id})
 env['product.pricelist'].search([]).write({'currency_id':thb.id})
 cr.commit()
 print('Local Odoo ready: Sales and Repair installed; THB company; randomized admin credentials set.')
