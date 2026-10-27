"""Staff cross-menu Demo: every staff menu (except the guide) is covered, staff-only, read-only."""
import json
from pathlib import Path
import re
import unittest

import test_integration_api as fixtures
import test_virtual_office as office
import app

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'static' / 'staff-demo.js').read_text(encoding='utf-8')
PAGES = set(re.findall(r"^    '(/[^']+)': ", SOURCE, re.M))


class TestStaffDemo(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.tokens = []
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (99,'fictional-admin','fictional','admin','Fiction Admin',1)")
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (98,'fictional-sales','fictional','sales','Fiction Sales',1)")

    def tearDown(self):
        for token in self.tokens:
            app.SESSIONS.pop(token, None)
        super().tearDown()

    def request(self, *args, **kwargs):
        return office.TestVirtualOffice.request(self, *args, **kwargs)

    def sidebar(self, html):
        nav = re.search(r'<aside class="sidebar".*?</aside>', html, re.S).group(0)
        return re.findall(r'<a href="([^"]+)"', nav)

    def test_every_staff_menu_except_guide_has_a_tour(self):
        for uid, role in ((99, 'admin'), (21, 'manager'), (12, 'technician_lead'), (11, 'technician'), (98, 'sales')):
            status, _, html = self.request('/field-service', user_id=uid, query='')
            self.assertEqual(status, 200, role)
            links = self.sidebar(html)
            self.assertIn('/guide', links)
            missing = [href for href in links if href not in PAGES and href not in ('/guide', '/field-service')]
            self.assertEqual(missing, [], role)
            self.assertIn('id="staff-demo-bar"', html, role)
            self.assertIn('เล่นต่อทุกเมนู', html)
            self.assertIn('/static/staff-demo.js', html)

    def test_customers_do_not_get_the_staff_demo(self):
        status, _, html = self.request('/customer/tickets', user_id=20, query='')
        self.assertEqual(status, 200)
        self.assertNotIn('staff-demo-bar', html)
        self.assertIn('customer-demo-bar', html)

    def test_static_rules(self):
        self.assertNotIn('/guide', PAGES)
        self.assertRegex(SOURCE, r"/\^\\/guide")                     # guide page shows no Demo
        for banned in ('.submit(', '.click(', 'XMLHttpRequest', 'speechSynthesis', 'localStorage'):
            self.assertNotIn(banned, SOURCE)
        lines = re.findall(r"step\('[^']*', '[^']*', '([^']*)'\)", SOURCE)
        self.assertGreaterEqual(len(lines), 50)
        manifest = json.loads((ROOT / 'static' / 'staff-demo-voice' / 'manifest.json').read_text(encoding='utf-8'))
        for text, file in manifest.items():
            self.assertIn(text, lines)
            self.assertRegex(file, r'^[a-f0-9]{16}\.mp3$')
            self.assertTrue((ROOT / 'static' / 'staff-demo-voice' / file).is_file())


if __name__ == '__main__':
    unittest.main()
