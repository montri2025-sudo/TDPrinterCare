"""Security regressions: fictional fixtures only, no PostgreSQL or network access.
Run: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
"""
import ast
import io
import ipaddress
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests' / '_stubs'))
import app


class SecurityTests(unittest.TestCase):
    def response(self, function, *args):
        self.headers = []
        body = function(*args, lambda status, headers: self.headers.append((status, dict(headers))))
        return b''.join(body)

    def conn(self, row):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = row
        return conn

    def test_center_logo_only_serves_registered_logo(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'CENTER_FILES_DIR', directory):
            center = Path(directory) / '1'; center.mkdir()
            (center / 'logo.png').write_bytes(b'FICTIONAL_LOGO')
            (center / 'cert.pdf').write_bytes(b'FICTIONAL_PRIVATE_DOCUMENT')
            conn = self.conn({'logo_filename': 'logo.png'})
            self.assertEqual(self.response(app.serve_center_logo, '/center-logo/1/logo.png', conn), b'FICTIONAL_LOGO')
            self.assertEqual(self.headers[0][0], '200 OK')
            self.response(app.serve_center_logo, '/center-logo/1/cert.pdf', conn)
            self.assertTrue(self.headers[0][0].startswith('404'))
            for path in ['/center-logo/1/../1/cert.pdf', '/center-logo/1/../../secret', '/center-logo/1/no.png']:
                self.response(app.serve_center_logo, path, conn)
                self.assertTrue(self.headers[0][0].startswith('404'))
            self.response(app.serve_center_doc, '/center-doc/1/cert.pdf', None)
            self.assertTrue(self.headers[0][0].startswith('403'))

    def test_media_role_and_center_matrix(self):
        row = {'center_id': 1, 'customer_id': 3, 'assigned_tech_id': 7}
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'UPLOADS_DIR', directory):
            ticket = Path(directory) / '1'; ticket.mkdir()
            (ticket / 'photo.png').write_bytes(b'FICTIONAL_PHOTO')
            cases = [(None, False), ({'role':'manager','center_id':2},False),
                     ({'role':'manager','center_id':None},False),
                     ({'role':'manager','center_id':1},True),
                     ({'role':'technician_lead','center_id':2},False),
                     ({'role':'technician_lead','center_id':1},True),
                     ({'role':'admin'},True), ({'role':'customer','customer_id':3},True),
                     ({'role':'customer','customer_id':4},False),
                     ({'role':'technician','user_id':7},True),
                     ({'role':'technician','user_id':8},False)]
            for user, allowed in cases:
                with self.subTest(user=user):
                    self.response(app.serve_media, '/media/1/photo.png', self.conn(row), user)
                    self.assertEqual(self.headers[0][0].startswith('200'), allowed)

    def test_rejects_active_or_mismatched_upload_before_writing(self):
        invalid = [('proof.html','image/png',b'<html>bad</html>'),
                   ('proof.png','image/png',b'<html>bad</html>'),
                   ('proof.svg','image/svg+xml',b'<svg/>'),
                   ('proof.png','image/jpeg',b'\x89PNG\r\n\x1a\n'),
                   ('proof.pdf','application/pdf',b'<html>bad</html>')]
        for name, mime, data in invalid:
            with self.subTest(name=name,mime=mime), patch('builtins.open') as opening:
                with self.assertRaises(ValueError):
                    app.save_device_proof('FICTIONAL-SN', {'filename':name,'content_type':mime,'data':data})
                opening.assert_not_called()

    def test_valid_images_and_pdf_still_save(self):
        fixtures = [('proof.png','image/png',b'\x89PNG\r\n\x1a\n'),
                    ('proof.jpg','image/jpeg',b'\xff\xd8\xff'),
                    ('proof.pdf','application/pdf',b'%PDF-1.7\nFICTIONAL')]
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DEVICE_PROOF_DIR', directory):
            for name,mime,data in fixtures:
                stored = app.save_device_proof('FICTIONAL-SN', {'filename':name,'content_type':mime,'data':data})
                self.assertEqual((Path(directory)/'FICTIONAL-SN'/stored).read_bytes(),data)

    def test_legacy_html_is_downloaded_with_sandbox(self):
        headers = dict(app._upload_headers('text/html', 100))
        self.assertEqual(headers['Content-Disposition'],'attachment')
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertIn('sandbox',headers['Content-Security-Policy'])
        self.assertNotIn('Content-Disposition',dict(app._upload_headers('image/png',100)))

    def test_oversized_and_invalid_posts_rejected_before_read_or_db(self):
        for length,status in [(str(app.MAX_REQUEST_BYTES+1),'413'),('-1','400'),('oops','400')]:
            with self.subTest(length=length), patch.object(app.db,'get_conn') as get_conn:
                stream=Mock()
                self.response(app.application, {'PATH_INFO':'/login','REQUEST_METHOD':'POST',
                                               'CONTENT_LENGTH':length,'wsgi.input':stream})
                self.assertTrue(self.headers[0][0].startswith(status))
                stream.read.assert_not_called(); get_conn.assert_not_called()
        with patch.object(app.db,'get_conn',return_value=self.conn(None)):
            self.response(app.application, {'PATH_INFO':'/nonexistent','REQUEST_METHOD':'POST',
                                           'CONTENT_LENGTH':'3','wsgi.input':io.BytesIO(b'abc')})
            self.assertTrue(self.headers[0][0].startswith('404'))

    def test_multipart_validation_after_csrf_extraction(self):
        body=(b'--boundary\r\nContent-Disposition: form-data; name="csrf_token"\r\n\r\nfictional-token\r\n'
              b'--boundary\r\nContent-Disposition: form-data; name="images"; filename="bad.html"\r\n'
              b'Content-Type: image/png\r\n\r\n<html>bad</html>\r\n--boundary--\r\n')
        env={'CONTENT_TYPE':'multipart/form-data; boundary=boundary','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body)}
        self.assertEqual(app._extract_csrf_token(env,body),'fictional-token')
        with self.assertRaises(app.HttpError) as error: app.parse_multipart(env)
        self.assertEqual(error.exception.status,400)

    def test_forwarded_headers_require_trusted_peer(self):
        with patch.object(app,'TRUSTED_PROXY_NETWORKS',()):
            for spoof in ['198.51.100.1','198.51.100.2','invalid']:
                self.assertEqual(app._client_ip({'REMOTE_ADDR':'192.0.2.9','HTTP_X_FORWARDED_FOR':spoof}),'192.0.2.9')
        with patch.object(app,'TRUSTED_PROXY_NETWORKS',(ipaddress.ip_network('192.0.2.0/24'),)):
            self.assertEqual(app._client_ip({'REMOTE_ADDR':'192.0.2.9','HTTP_X_FORWARDED_FOR':'203.0.113.1, 198.51.100.7'}),'198.51.100.7')
            self.assertEqual(app._client_ip({'REMOTE_ADDR':'192.0.2.9','HTTP_X_FORWARDED_FOR':'invalid'}),'192.0.2.9')

    def test_rotating_spoofed_ip_does_not_bypass_login_limit(self):
        app.LOGIN_ATTEMPTS.clear()
        conn=self.conn(None)
        try:
            with patch.object(app,'TRUSTED_PROXY_NETWORKS',()), patch.object(app,'render_login',return_value=b'error'):
                for attempt in range(app.LOGIN_MAX_ATTEMPTS+1):
                    body=b'username=fictional&password=incorrect'
                    app.login_submit({'CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),
                                      'REMOTE_ADDR':'192.0.2.9','HTTP_X_FORWARDED_FOR':f'198.51.100.{attempt}'},None,conn,None)
            self.assertEqual(conn.execute.call_count,app.LOGIN_MAX_ATTEMPTS)
        finally: app.LOGIN_ATTEMPTS.clear()

    def test_demo_seed_is_off_without_explicit_opt_in(self):
        source=(ROOT/'db.py').read_text()
        assignment=next(n for n in ast.parse(source).body
                        if isinstance(n,ast.Assign) and any(getattr(t,'id',None)=='SEED_DEMO_DATA' for t in n.targets))
        for configured, expected in [(None,False),('0',False),('1',True),('true',False)]:
            with patch.dict(os.environ,{},clear=True):
                if configured is not None: os.environ['SEED_DEMO_DATA']=configured
                scope={'os':os}
                exec(compile(ast.Module(body=[assignment],type_ignores=[]),'db.py','exec'),scope)
                self.assertEqual(scope['SEED_DEMO_DATA'],expected)

    def test_changed_templates_compile(self):
        for name in ['base', 'admin_new_ticket', 'admin_customers', 'sales_new',
                     'sales_order_detail', 'admin_dashboard', 'admin_reports', 'customer_dashboard']:
            with self.subTest(template=name):
                app.env.get_template(name + '.html')

    @unittest.skipUnless(shutil.which('node'), 'Node needed for DOM regression')
    def test_report_popup_escapes_customer_and_device_text(self):
        base = (ROOT/'templates'/'base.html').read_text()
        helper = base[base.index('  function escapeHtmlText('):base.index('  // อ่านสถานะ')]
        report = (ROOT/'templates'/'admin_reports.html').read_text()
        popup = report[report.index('  function openTicketReportDetail('):report.index('  function closeTicketReportDetail(')]
        script = '''const assert = require('node:assert/strict');
const payload = '<img src=x onerror="throw 1">';
const elements = {trBody: {}, ticketReportOverlay: {style: {}}};
const document = {getElementById: id => elements[id]};
const row = {ticket_id: 1, status: 'New', status_history: [{note: payload}],
 model: payload, customer_name: payload, customer_phone: payload,
 tech_name: payload, center_name: payload, issue_category: payload, description: payload};
const TICKET_REPORTS_BY_ID = {1: row};
const TR_STATUSES = ['New'];
const TR_STATUS_LABELS = {New: 'New'};
const TR_NEXT_STEP_HINTS = {};
''' + helper + popup + '''
openTicketReportDetail(1);
assert.ok(!elements.trBody.innerHTML.includes(payload));
assert.ok(elements.trBody.innerHTML.includes('&lt;img'));
assert.equal(elements.ticketReportOverlay.style.display, 'flex');
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node needed for DOM regression')
    def test_device_options_keep_untrusted_serial_and_model_as_text(self):
        source = (ROOT/'templates'/'admin_new_ticket.html').read_text()
        start = source.index('  function populateDeviceSelect(')
        function = source[start:source.index("  document.getElementById('bookingDateInput')", start)]
        script = '''const assert = require('node:assert/strict');
const payload = '\"><img src=x onerror="throw 1">';
const select = {children: [], replaceChildren() {this.children = [];},
 appendChild(child) {this.children.push(child);},
 set innerHTML(value) {throw new Error('Device data must not be parsed as HTML');}};
const document = {getElementById: () => select, createElement: () => ({})};
const DEVICES_BY_CUSTOMER = {1: [{sn: payload, model: payload, has_open_ticket: true}]};
''' + function + '''
populateDeviceSelect(1);
assert.equal(select.children[0].value, payload);
assert.ok(select.children[0].textContent.includes(payload));
assert.equal(select.children[0].disabled, true);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node needed for DOM regression')
    def test_customer_picker_treats_html_as_text_in_all_four_pages(self):
        for page in ['admin_new_ticket','admin_customers','sales_new','sales_order_detail']:
            source=(ROOT/'templates'/f'{page}.html').read_text()
            function_name = 'renderEditCustomerPickerResults' if page == 'sales_order_detail' else 'renderCustomerPickerResults'
            start = source.index('  function ' + function_name + '(list)')
            end = source.index('\n  function ', start + 5)
            function = source[start:end]
            script='''const assert = require('node:assert/strict');
class Element {
 constructor(tag) { this.tag=tag; this.children=[]; }
 appendChild(child) { this.children.push(child); }
 set innerHTML(value) { assert.equal(value, ''); this.children=[]; }
}
const container = new Element('div');
const document = {getElementById:()=>container,createElement:tag=>new Element(tag)};
'''+function+'''
const payload='<img src=x onerror="throw 1">';
FUNCTION_NAME([{id:1,name:payload,phone:payload}]);
assert.equal(container.children[0].children[0].textContent,payload);
assert.equal(container.children[0].children[1].textContent,payload);
'''
            with self.subTest(page=page):
                result=subprocess.run(['node','-e',script.replace('FUNCTION_NAME',function_name)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__': unittest.main()
